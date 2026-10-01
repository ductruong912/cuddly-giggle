"""HTTP contracts, upload guards, readiness and pipeline concurrency."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import time
from typing import Any

from api.application import app
from api.dependencies import get_local_extraction_service, get_pipeline_limiters
from core.domain.schemas import ParseDecision, ParseResponse
from services.document_extraction import DocumentExtractionService


def test_the_expected_routes_are_registered() -> None:
    paths = {getattr(route, "path", None) for route in app.routes}

    assert {"/healthz", "/v1/extract/local", "/v1/doc/ocr"} <= paths
    assert "/v1/extract/online" not in app.openapi()["paths"]


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

    release = threading.Event()

    async def body(client):
        limiters = get_pipeline_limiters()
        limiters.ocr.execution_timeout_seconds = 0.1
        try:
            await limiters.ocr.run(release.wait, 5)
        except StageTimedOut:
            pass
        response = await client.get("/readyz")
        health = await client.get("/healthz")
        release.set()
        assert health.status_code == 200
        return response

    response = api(body)

    assert response.status_code == 503
    payload = response.json()
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


def test_a_rejected_upload_leaves_no_temp_file(api: Any) -> None:
    async def body(client):
        response = await client.post(
            "/v1/extract/local",
            files={"file": ("big.pdf", b"P" * 9000, "application/pdf")},
        )
        assert response.status_code == 413
        staging = Path(os.environ["DOC_TEMP_DIR"])
        return sorted(staging.glob("*")) if staging.is_dir() else []

    assert api(body) == []


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


def test_concurrent_uploads_all_succeed(api: Any, valid_order: dict) -> None:
    parser = BlockingParser(seconds=0.4)

    async def body(client):
        install_pipeline(parser, valid_order)
        return await asyncio.gather(*(upload(client, index) for index in range(6)))

    responses = api(body)

    assert [r.status_code for r in responses] == [200] * 6
    assert parser.peak_in_flight == 2, "OCR_MAX_CONCURRENCY is 2"


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


def test_a_saturated_stage_sheds_load(api: Any, valid_order: dict) -> None:
    """Over the queue timeout, requests are refused rather than queued forever."""
    parser = BlockingParser(seconds=2.5)

    async def body(client):
        install_pipeline(parser, valid_order)
        return await asyncio.gather(*(upload(client, index) for index in range(6)))

    responses = api(body)
    codes = [r.status_code for r in responses]

    assert 503 in codes, f"nothing was shed: {codes}"
    assert 200 in codes, f"nothing got through: {codes}"
    assert all("retry-after" in r.headers for r in responses if r.status_code == 503)


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
