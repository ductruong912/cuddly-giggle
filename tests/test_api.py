"""API contract for POST /v1/doc/parse, with a stub orchestrator (no real OCR)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.api.routes as routes
from app.api.application import app
from app.api.routes import get_orchestrator
from app.domain.schemas import ParseDecision, ParseResponse


class StubOrchestrator:
    def __init__(self, markdown: str | None) -> None:
        self._markdown = markdown

    def parse(self, input_path, options) -> ParseResponse:
        return ParseResponse(
            request_id="req_test",
            decision=ParseDecision(reason="stubbed"),
            pages=[], blocks=[], tables=[], reading_order=[],
            markdown=self._markdown,
        )


@pytest.fixture
def client(monkeypatch):
    # Never touch disk for artifact saving during API tests.
    monkeypatch.setattr(routes, "save_parse_artifacts", lambda **kwargs: [])

    def _make(markdown="# hello"):
        app.dependency_overrides[get_orchestrator] = lambda: StubOrchestrator(markdown)
        return TestClient(app)

    yield _make
    app.dependency_overrides.clear()


def test_healthz_ok():
    assert TestClient(app).get("/healthz").json() == {"status": "ok"}


def test_parse_returns_markdown(client):
    resp = client("# hello").post(
        "/v1/doc/parse",
        files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert resp.text == "# hello"


def test_unsupported_extension_is_rejected(client):
    resp = client().post(
        "/v1/doc/parse",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400


def test_empty_markdown_is_server_error(client):
    resp = client(markdown=None).post(
        "/v1/doc/parse",
        files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert resp.status_code == 500
