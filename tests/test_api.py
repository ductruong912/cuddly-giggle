from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.dependencies import get_orchestrator
from app.application import app
from app.domain.schemas import ParseDecision, ParseResponse, QualityFlags


class StubOrchestrator:
    def parse(self, input_path: str, options):  # type: ignore[no-untyped-def]
        return ParseResponse(
            request_id="req_test",
            decision=ParseDecision(status="pass", reason="ok"),
            pages=[],
            blocks=[],
            tables=[],
            reading_order=[],
            quality_flags=QualityFlags(),
            markdown="# Parsed",
            review_queued=False,
            review_reason=None,
        )


def test_parse_api_contract(monkeypatch) -> None:
    app.dependency_overrides[get_orchestrator] = lambda: StubOrchestrator()
    client = TestClient(app)

    try:
        resp = client.post(
            "/v1/doc/parse",
            files={"file": ("sample.png", b"not-real-image", "image/png")},
            data={"lang_hint": "vi", "output_format": "both", "enable_fallback": "true"},
        )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert "request_id" in body
    assert body["decision"]["status"] == "pass"
    assert "pages" in body


def test_parse_api_auto_save_output(monkeypatch) -> None:
    app.dependency_overrides[get_orchestrator] = lambda: StubOrchestrator()
    client = TestClient(app)

    try:
        resp = client.post(
            "/v1/doc/parse",
            files={"file": ("sample.png", b"not-real-image", "image/png")},
            data={
                "lang_hint": "vi",
                "output_format": "both",
                "enable_fallback": "false",
                "output_basename": "sample_doc",
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert "saved_files" in body
    assert len(body["saved_files"]) >= 1
    for p in body["saved_files"]:
        path_obj = Path(p)
        assert path_obj.exists()
        path_obj.unlink(missing_ok=True)


def test_parse_api_auto_save_output_markdown_only(monkeypatch) -> None:
    app.dependency_overrides[get_orchestrator] = lambda: StubOrchestrator()
    client = TestClient(app)

    try:
        resp = client.post(
            "/v1/doc/parse",
            files={"file": ("sample.png", b"not-real-image", "image/png")},
            data={
                "lang_hint": "vi",
                "output_format": "markdown",
                "enable_fallback": "false",
                "output_basename": "sample_doc_md",
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    saved = body["saved_files"]
    assert len(saved) == 1
    assert saved[0].endswith(".md")
    for p in saved:
        path_obj = Path(p)
        assert path_obj.exists()
        path_obj.unlink(missing_ok=True)


def test_parse_api_auto_save_output_json_only(monkeypatch) -> None:
    app.dependency_overrides[get_orchestrator] = lambda: StubOrchestrator()
    client = TestClient(app)

    try:
        resp = client.post(
            "/v1/doc/parse",
            files={"file": ("sample.png", b"not-real-image", "image/png")},
            data={
                "lang_hint": "vi",
                "output_format": "json",
                "enable_fallback": "false",
                "output_basename": "sample_doc_json",
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    saved = body["saved_files"]
    assert len(saved) == 1
    assert saved[0].endswith(".json")
    for p in saved:
        path_obj = Path(p)
        assert path_obj.exists()
        path_obj.unlink(missing_ok=True)
