"""HTTP guards, concurrency, OCR responses and the optional playground."""
from __future__ import annotations

import os
import asyncio
import time
from pathlib import Path
from typing import Any
from dataclasses import replace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI

from api.application import app
from api.dependencies import (
    get_local_extraction_service,
    get_pipeline_limiters,
    ensure_gpu_gguf_runtime,
    get_orchestrator,
)
from core.domain.schemas import ParseDecision, ParseResponse
from services.document_extraction import DocumentExtractionService
from api.frontend import register_frontend
from api.routes import SUPPORTED_INPUT_SUFFIXES
from config.config import settings


def test_healthz_reports_stage_occupancy(api: Any) -> None:
    async def body(client):
        return await client.get("/healthz")

    response = api(body)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["stages"]["ocr"]["max_concurrency"] == 2


def test_readyz_reports_ready_when_dependencies_are_fine(api: Any) -> None:
    async def body(client):
        return await client.get("/readyz")

    response = api(body)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["checks"]["llm_credentials"] == "ok"
    assert payload["checks"]["stages"] == "ok"


def test_readyz_sheds_traffic_when_a_stage_is_degraded(api: Any) -> None:
    """A held slot means the instance is running below capacity; stop routing to it."""
    import threading

    from services.concurrency import StageTimedOut
    from api.dependencies import get_pipeline_limiters

    release = threading.Event()

    async def body(client):
        limiters = get_pipeline_limiters()
        limiters.ocr.execution_timeout_seconds = 0.1
        try:
            await limiters.ocr.run(release.wait, 5)
        except StageTimedOut:
            pass
        health = await client.get("/healthz")
        ready = await client.get("/readyz")
        release.set()
        return health, ready

    health, ready = api(body)

    assert health.status_code == 200
    assert ready.status_code == 503
    payload = ready.json()
    assert payload["status"] == "not_ready"
    assert payload["degraded_stages"] == ["ocr"]
    assert payload["stages"]["ocr"]["abandoned"] == 1


def test_the_worker_pool_is_sized_from_the_stage_limits(api: Any) -> None:
    """Threads must outnumber the slots that use them, or stages starve."""

    async def body(client):
        from anyio import to_thread

        await client.get("/healthz")
        return to_thread.current_default_thread_limiter().total_tokens

    assert api(body) == 10, "OCR_MAX_CONCURRENCY + LLM_MAX_CONCURRENCY + 4"


def test_an_unaccepted_content_type_is_refused(api: Any) -> None:
    async def body(client):
        return await client.post(
            "/v1/extract/local", content=b"x", headers={"content-type": "application/xml"}
        )

    assert api(body).status_code == 415


def test_an_unsupported_file_type_is_refused(api: Any) -> None:
    async def body(client):
        return await client.post(
            "/v1/extract/local",
            files={"file": ("payload.exe", b"binary", "application/octet-stream")},
        )

    assert api(body).status_code == 400


def test_json_without_a_markdown_key_is_refused(api: Any) -> None:
    async def body(client):
        return await client.post("/v1/extract/local", json={"not_markdown": "x"})

    assert api(body).status_code == 400


def test_an_oversized_upload_is_refused(api: Any) -> None:
    """Rejected while streaming, so an over-cap file is never written whole."""

    async def body(client):
        response = await client.post(
            "/v1/extract/local",
            files={"file": ("big.pdf", b"P" * 9000, "application/pdf")},
        )
        staging = Path(os.environ["DOC_TEMP_DIR"])
        assert not list(staging.glob("*"))
        return response

    assert api(body).status_code == 413


def test_a_missing_file_field_is_refused(api: Any) -> None:
    async def body(client):
        return await client.post(
            "/v1/extract/local", files={"wrong_field": ("a.pdf", b"x", "application/pdf")}
        )

    assert api(body).status_code == 400


class BlockingParser:
    """Occupies a worker thread for a fixed time, recording peak concurrency."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.in_flight = 0
        self.peak_in_flight = 0

    def parse(self, input_path: str, options: object = None, *, request_id: str | None = None):
        del input_path, options
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            time.sleep(self.seconds)
            return ParseResponse(
                request_id=request_id or "req_test",
                decision=ParseDecision(reason="blocking stub"),
                pages=[],
                blocks=[],
                tables=[],
                reading_order=[],
                markdown="# stub\n\nbody",
            )
        finally:
            self.in_flight -= 1


class StubExtractor:
    """Returns a record that satisfies every deterministic check."""

    def __init__(self, order: dict) -> None:
        self.order = order

    def extract(self, parse_response: ParseResponse, *, correction: str | None = None) -> dict:
        del parse_response, correction
        return self.order


def install_pipeline(parser: BlockingParser, order: dict) -> None:
    """Point the local route at the stand-in parser for one test."""
    app.dependency_overrides[get_local_extraction_service] = lambda: DocumentExtractionService(
        parser, StubExtractor(order), get_pipeline_limiters(), route_label="test"
    )


async def upload(client: Any, index: int):
    return await client.post(
        "/v1/extract/local",
        files={"file": (f"doc{index}.pdf", b"%PDF-1.4 stub", "application/pdf")},
    )


def test_concurrent_uploads_respect_slots_and_batch_queued_work(api: Any, valid_order: dict) -> None:
    parser = BlockingParser(seconds=0.4)

    async def body(client):
        install_pipeline(parser, valid_order)
        started = time.perf_counter()
        responses = await asyncio.gather(*(upload(client, index) for index in range(6)))
        return responses, time.perf_counter() - started

    responses, elapsed = api(body)

    assert [r.status_code for r in responses] == [200] * 6
    assert parser.peak_in_flight == 2, "OCR_MAX_CONCURRENCY is 2: not more, and not serialised"
    # Six jobs through two slots should finish in three batches.
    assert 0.8 < elapsed < 2.0, f"took {elapsed:.2f}s"


def test_the_event_loop_stays_responsive_while_ocr_runs(api: Any, valid_order: dict) -> None:
    """The bug this replaced: OCR ran on the event loop and froze every route."""
    parser = BlockingParser(seconds=0.5)

    async def body(client):
        install_pipeline(parser, valid_order)
        uploads = asyncio.gather(*(upload(client, index) for index in range(6)))
        await asyncio.sleep(0.15)

        started = time.perf_counter()
        health = await client.get("/healthz")
        latency = time.perf_counter() - started

        await uploads
        assert health.status_code == 200
        return latency

    assert api(body) < 0.15


def test_a_saturated_stage_sheds_load_with_retry_after(api: Any, valid_order: dict) -> None:
    """Over the queue timeout, requests are refused rather than queued forever."""
    parser = BlockingParser(seconds=2.5)

    async def body(client):
        install_pipeline(parser, valid_order)
        return await asyncio.gather(*(upload(client, index) for index in range(6)))

    responses = api(body)
    codes = [r.status_code for r in responses]

    assert 503 in codes, f"nothing was shed: {codes}"
    assert 200 in codes, f"nothing got through: {codes}"
    rejected = [r for r in responses if r.status_code == 503]
    assert all("retry-after" in r.headers for r in rejected)


def test_the_response_carries_its_validation_verdict(api: Any, valid_order: dict) -> None:
    parser = BlockingParser(seconds=0.05)

    async def body(client):
        install_pipeline(parser, valid_order)
        return await upload(client, 0)

    payload = api(body).json()

    assert payload["validation"]["status"] == "valid"
    assert payload["validation"]["attempts"] == 1
    assert payload["validation"]["healed"] is False


def test_a_needs_review_record_still_returns_200(api: Any, valid_order: dict) -> None:
    """There is no review queue, so the verdict travels in the response body."""
    shifted = {**valid_order, "items": [dict(valid_order["items"][0])]}
    shifted["items"][0]["extension"] = 500000
    parser = BlockingParser(seconds=0.05)

    async def body(client):
        install_pipeline(parser, shifted)
        return await upload(client, 0)

    response = api(body)

    assert response.status_code == 200
    payload = response.json()
    assert payload["validation"]["status"] == "needs_review"
    assert payload["validation"]["attempts"] == 3
    assert payload["data"] == shifted, "the record is returned for a human to judge"
    assert any("line total mismatch" in issue["message"] for issue in payload["validation"]["issues"])


def request(application: FastAPI, path: str) -> httpx.Response:
    async def run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://test"
        ) as client:
            return await client.get(path)

    return asyncio.run(run())


def test_ui_config_contains_only_public_ocr_limits(api: Any) -> None:
    async def body(client):
        return await client.get("/v1/ui/config")

    response = api(body)
    assert response.status_code == 200
    assert response.json() == {
        "supported_suffixes": sorted(SUPPORTED_INPUT_SUFFIXES),
        "max_upload_bytes": settings.max_upload_bytes,
        "pdf_max_pages": settings.pdf_max_pages,
    }
    assert ".md" not in response.json()["supported_suffixes"]


@pytest.mark.parametrize("present", [False, True])
def test_frontend_is_optional_and_does_not_capture_api_paths(tmp_path: Path, present: bool) -> None:
    application = FastAPI()
    if present:
        (tmp_path / "index.html").write_text("<html>OCR Playground</html>", encoding="utf-8")
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "app.js").write_text("// synthetic asset", encoding="utf-8")
    register_frontend(application, replace(settings, frontend_dist_dir=str(tmp_path)))

    for path in ("/", "/playground", "/playground/"):
        response = request(application, path)
        assert response.status_code == (200 if present else 404)
        if present:
            assert "text/html" in response.headers["content-type"]
            assert response.headers["cache-control"] == "no-cache"
    assert request(application, "/v1/unknown").status_code == 404
    assert request(application, "/not-a-page").status_code == 404
    assert request(application, "/docs").status_code == 200
    assert request(application, "/openapi.json").status_code == 200
    assert request(application, "/assets/app.js").status_code == (200 if present else 404)
    assert request(application, "/assets/missing.js").status_code == 404
    assert request(application, "/assets/../index.html").status_code == 404


def test_incomplete_frontend_build_does_not_break_api(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html>incomplete</html>", encoding="utf-8")
    application = FastAPI()
    register_frontend(application, replace(settings, frontend_dist_dir=str(tmp_path)))
    assert request(application, "/").status_code == 404


@pytest.mark.parametrize("path", ["/v1/doc/ocr", "/v1/doc/ocr/result", "/v1/doc/ocr/result?include_preview=true"])
def test_ocr_works_without_openai_or_database_and_cleans_upload(
    api: Any, monkeypatch: pytest.MonkeyPatch, parse_response: Any, temp_root: Path, path: str
) -> None:
    import api.application as application_module
    import api.dependencies as dependencies
    import api.routes as routes
    import services.llm_extraction as extraction

    ocr_settings = replace(settings, openai_api_key="", database_url="")
    monkeypatch.setattr(application_module, "settings", ocr_settings)
    monkeypatch.setattr(dependencies, "settings", ocr_settings)
    monkeypatch.setattr(routes, "settings", ocr_settings)
    forbidden = Mock(side_effect=AssertionError("OCR must not initialize OpenAI or persistence"))
    monkeypatch.setattr(extraction.LLMExtractionService, "_create_client", forbidden)
    monkeypatch.setattr(dependencies, "get_local_extraction_service", forbidden)
    monkeypatch.setattr(routes, "save_parse_artifacts", lambda *_: [])
    parser = Mock()
    from core.domain.schemas import Block, BlockType, PageGeometry, PageParseResult, Point, Table, TableCell

    block = Block(block_id="ocr_block", type=BlockType.text, content="Synthetic",
                  bbox=[Point(x=0, y=0), Point(x=100, y=0), Point(x=100, y=50), Point(x=0, y=50)])
    table = Table(table_id="ocr_table", page_index=0, cells=[TableCell(row=0, col=0, text="Synthetic")])
    parse_response.pages = [PageParseResult(page_index=0, blocks=[block], tables=[table],
                                          reading_order=[block.block_id],
                                          geometry=PageGeometry(width=200, height=300, coordinate_space="original"))]
    parse_response.blocks = [block]
    parse_response.tables = [table]
    parse_response.reading_order = [block.block_id]
    from core.engines.preview import preview_capture_enabled
    captured = []
    def parse(_):
        captured.append(preview_capture_enabled())
        return parse_response
    parser.parse.side_effect = parse

    async def body(client):
        # Overrides are applied here because the shared fixture resets singletons first.
        app.dependency_overrides[get_orchestrator] = lambda: parser
        app.dependency_overrides[ensure_gpu_gguf_runtime] = lambda: None
        health = await client.get("/healthz")
        ready = await client.get("/readyz")
        result = await client.post(
            path, files={"file": ("synthetic.pdf", b"synthetic", "application/pdf")}
        )
        return health, ready, result

    health, ready, result = api(body)
    assert health.status_code == 200
    assert ready.status_code == 503  # Full-pipeline readiness still checks LLM credentials.
    assert result.status_code == 200
    if path.split("?")[0].endswith("/result"):
        assert result.json() == parse_response.model_dump(mode="json")
    else:
        assert result.headers["content-type"].startswith("text/markdown")
        assert result.text == parse_response.markdown
    parser.parse.assert_called_once()
    assert captured == ["include_preview=true" in path]
    assert not preview_capture_enabled()
    forbidden.assert_not_called()
    assert list((temp_root / "staging").iterdir()) == []


@pytest.mark.parametrize("failure", [False, True])
def test_structured_ocr_cleans_upload_on_empty_result_or_parser_error(
    api: Any, monkeypatch: pytest.MonkeyPatch, parse_response: Any, temp_root: Path, failure: bool
) -> None:
    import api.routes as routes

    parse_response.markdown = None
    parser = Mock()
    parser.parse.return_value = parse_response
    if failure:
        parser.parse.side_effect = RuntimeError("synthetic OCR failure")
    saved = Mock()
    monkeypatch.setattr(routes, "save_parse_artifacts", saved)

    async def body(client):
        app.dependency_overrides[get_orchestrator] = lambda: parser
        app.dependency_overrides[ensure_gpu_gguf_runtime] = lambda: None
        return await client.post("/v1/doc/ocr/result", files={"file": ("synthetic.png", b"synthetic")})

    response = api(body)
    assert response.status_code >= 400
    if not failure:
        assert response.status_code == 422
    assert list((temp_root / "staging").iterdir()) == []
