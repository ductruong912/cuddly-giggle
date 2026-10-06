"""The OCR UI uses the existing parser without requiring extraction services."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI

from api.application import app
from api.dependencies import ensure_gpu_gguf_runtime, get_orchestrator
from api.frontend import register_frontend
from api.routes import SUPPORTED_INPUT_SUFFIXES
from config.config import settings


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
