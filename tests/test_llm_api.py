"""HTTP contract for the independent LLM extraction upload endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.application import app
from app.api.routes import get_llm_extractor, get_orchestrator
from app.domain.schemas import ParseDecision, ParseResponse


class StubOrchestrator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def parse(self, input_path, options) -> ParseResponse:
        self.calls.append((input_path, options))
        return ParseResponse(
            request_id="req_ocr", decision=ParseDecision(reason="stubbed"),
            pages=[], blocks=[], tables=[], reading_order=[], markdown="# Invoice 1",
        )


class StubExtractor:
    def extract(self, response: ParseResponse) -> dict[str, object]:
        assert response.markdown == "# Invoice 1"
        return {"document_type": "invoice", "fields": [], "items": []}


@pytest.fixture
def client():
    orchestrator = StubOrchestrator()
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    app.dependency_overrides[get_llm_extractor] = lambda: StubExtractor()
    yield TestClient(app), orchestrator
    app.dependency_overrides.clear()


def test_llm_extract_returns_structured_data(client):
    http, orchestrator = client

    response = http.post(
        "/v1/llm/extract",
        files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "request_id": "req_ocr",
        "ocr": {"decision": "stubbed", "page_count": 0},
        "data": {"document_type": "invoice", "fields": [], "items": []},
    }
    assert len(orchestrator.calls) == 1


def test_llm_extract_rejects_an_unsupported_file(client):
    http, orchestrator = client

    response = http.post(
        "/v1/llm/extract",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 400
    assert orchestrator.calls == []
