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


def test_ocr_works_without_openai_or_database_and_cleans_upload(
    api: Any, monkeypatch: pytest.MonkeyPatch, parse_response: Any, temp_root: Path
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
    parser.parse.return_value = parse_response

    async def body(client):
        # Overrides are applied here because the shared fixture resets singletons first.
        app.dependency_overrides[get_orchestrator] = lambda: parser
        app.dependency_overrides[ensure_gpu_gguf_runtime] = lambda: None
        health = await client.get("/healthz")
        ready = await client.get("/readyz")
        result = await client.post(
            "/v1/doc/ocr", files={"file": ("synthetic.pdf", b"synthetic", "application/pdf")}
        )
        return health, ready, result

    health, ready, result = api(body)
    assert health.status_code == 200
    assert ready.status_code == 503  # Full-pipeline readiness still checks LLM credentials.
    assert result.status_code == 200
    assert result.headers["content-type"].startswith("text/markdown")
    assert result.text == parse_response.markdown
    parser.parse.assert_called_once()
    forbidden.assert_not_called()
    assert list((temp_root / "staging").iterdir()) == []
