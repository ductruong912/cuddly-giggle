"""HTTP contract for the independent LLM extraction upload endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.application import app
from app.api.routes import get_llm_extractor, get_orchestrator
from app.domain.schemas import ParseDecision, ParseResponse
from app.services.llm_extraction import LLMExtractionInputTooLarge, LLMExtractionUnavailable


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
        return {
            "po_number": "PO-001",
            "po_date": "2026-07-13",
            "items": [],
        }


class TooLargeExtractor:
    def extract(self, response: ParseResponse) -> dict[str, object]:
        raise LLMExtractionInputTooLarge("OCR text exceeds configured input limit")


class UnavailableExtractor:
    def extract(self, response: ParseResponse) -> dict[str, object]:
        raise LLMExtractionUnavailable("OpenAI extraction is temporarily unavailable")


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
        "data": {"po_number": "PO-001", "po_date": "2026-07-13", "items": []},
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


def test_llm_extract_from_ocr_uses_the_complete_uploaded_markdown_file(client):
    class MarkdownExtractor:
        def __init__(self) -> None:
            self.markdown: str | None = None

        def extract(self, response: ParseResponse) -> dict[str, object]:
            self.markdown = response.markdown
            return {"po_number": "PO-001", "po_date": "", "items": []}

    http, orchestrator = client
    extractor = MarkdownExtractor()
    app.dependency_overrides[get_llm_extractor] = lambda: extractor
    markdown = "# Parsed PO\n\n| Item | Quantity |\n| --- | --- |\n| TP-1 | 2 |"

    response = http.post(
        "/v1/llm/extract-from-ocr",
        files={"file": ("purchase-order.md", markdown.encode("utf-8"), "text/markdown")},
    )

    assert response.status_code == 200
    assert extractor.markdown == markdown
    assert orchestrator.calls == []
    assert response.json()["data"]["po_number"] == "PO-001"


def test_llm_extract_returns_413_for_context_over_limit(client):
    http, _ = client
    app.dependency_overrides[get_llm_extractor] = lambda: TooLargeExtractor()

    response = http.post(
        "/v1/llm/extract",
        files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )

    assert response.status_code == 413


def test_llm_extract_returns_503_for_provider_failure(client):
    http, _ = client
    app.dependency_overrides[get_llm_extractor] = lambda: UnavailableExtractor()

    response = http.post(
        "/v1/llm/extract",
        files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )

    assert response.status_code == 503
