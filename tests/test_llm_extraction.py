"""Unit tests for the OpenAI structured-extraction service."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.domain.schemas import ParseDecision, ParseResponse
from app.prompts.prompt import EXTRACTION_JSON_SCHEMA
from app.services.llm_extraction import (
    LLMExtractionError,
    LLMExtractionInputTooLarge,
    LLMExtractionService,
    LLMExtractionUnavailable,
)


class FakeResponses:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.output_text)


class FakeOpenAIClient:
    def __init__(self, output_text: str) -> None:
        self.responses = FakeResponses(output_text)


class UnavailableResponses:
    def create(self, **kwargs):
        raise TimeoutError("provider timed out")


class UnavailableOpenAIClient:
    responses = UnavailableResponses()


class ProviderStatusError(Exception):
    status_code = 503


class ProviderStatusResponses:
    def create(self, **kwargs):
        raise ProviderStatusError("upstream unavailable")


class ProviderStatusClient:
    responses = ProviderStatusResponses()


def make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "openai_api_key": "test-key",
        "openai_model": "gpt-5-mini",
        "openai_timeout_seconds": 10.0,
        "openai_max_retries": 0,
        "llm_max_input_chars": 1_000,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def make_parse_response(markdown: str | None) -> ParseResponse:
    return ParseResponse(
        request_id="req_test",
        decision=ParseDecision(reason="stubbed"),
        pages=[], blocks=[], tables=[], reading_order=[], markdown=markdown,
    )


def test_extract_uses_prompt_schema_and_returns_parsed_json():
    client = FakeOpenAIClient(
        '{"po_number":"PO-001","po_date":"2026-07-13","items":[]}'
    )
    service = LLMExtractionService(client=client, app_settings=make_settings())

    assert service.extract(make_parse_response("Invoice number: 001")) == {
        "po_number": "PO-001", "po_date": "2026-07-13", "items": [],
    }
    request = client.responses.calls[0]
    assert request["model"] == "gpt-5-mini"
    assert request["text"]["format"]["schema"] == EXTRACTION_JSON_SCHEMA


def test_default_schema_models_po_line_items_and_missing_values_as_empty_strings():
    properties = EXTRACTION_JSON_SCHEMA["properties"]

    assert set(properties) == {"po_number", "po_date", "items"}
    assert properties["po_number"] == {"type": "string"}
    assert properties["po_date"] == {"type": "string"}
    assert properties["items"]["items"]["properties"] == {
        "customer_item_code": {"type": "string"},
        "toto_item_code": {"type": "string"},
        "quantity": {"type": "string"},
        "unit_price": {"type": "string"},
    }


def test_extract_rejects_empty_ocr_content():
    service = LLMExtractionService(
        client=FakeOpenAIClient("{}"), app_settings=make_settings(),
    )

    with pytest.raises(LLMExtractionError, match="OCR produced no usable text"):
        service.extract(make_parse_response(None))


def test_extract_rejects_context_over_configured_limit():
    service = LLMExtractionService(
        client=FakeOpenAIClient("{}"), app_settings=make_settings(llm_max_input_chars=3),
    )

    with pytest.raises(LLMExtractionInputTooLarge, match="input limit"):
        service.extract(make_parse_response("four"))


def test_extract_maps_provider_timeout_to_unavailable():
    service = LLMExtractionService(
        client=UnavailableOpenAIClient(), app_settings=make_settings(),
    )

    with pytest.raises(LLMExtractionUnavailable, match="temporarily unavailable"):
        service.extract(make_parse_response("Invoice 001"))


def test_extract_maps_provider_5xx_to_unavailable():
    service = LLMExtractionService(
        client=ProviderStatusClient(), app_settings=make_settings(),
    )

    with pytest.raises(LLMExtractionUnavailable, match="temporarily unavailable"):
        service.extract(make_parse_response("Invoice 001"))
