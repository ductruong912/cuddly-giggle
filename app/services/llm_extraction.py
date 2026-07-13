"""OpenAI Structured Outputs adapter for normalized OCR results."""
from __future__ import annotations

import json
from typing import Any

from app.core.config import Settings, settings
from app.domain.schemas import ParseResponse
from app.prompts.prompt import (
    EXTRACTION_INSTRUCTIONS,
    EXTRACTION_JSON_SCHEMA,
    EXTRACTION_SCHEMA_NAME,
)


class LLMExtractionError(RuntimeError):
    """The document could not be converted to a usable extraction result."""


class LLMExtractionInputTooLarge(LLMExtractionError):
    """OCR text exceeds the configured model-input limit."""


class LLMExtractionUnavailable(LLMExtractionError):
    """The OpenAI provider could not complete the request."""


class LLMExtractionService:
    def __init__(self, client: Any | None = None, app_settings: Settings = settings) -> None:
        self.settings = app_settings
        self.client = client or self._create_client()

    def extract(self, parse_response: ParseResponse) -> dict[str, Any]:
        markdown = (parse_response.markdown or "").strip()
        if not markdown:
            raise LLMExtractionError("OCR produced no usable text")
        if len(markdown) > self.settings.llm_max_input_chars:
            raise LLMExtractionInputTooLarge("OCR text exceeds configured input limit")

        try:
            response = self.client.responses.create(
                model=self.settings.openai_model,
                instructions=EXTRACTION_INSTRUCTIONS,
                input=f"<document>\n{markdown}\n</document>",
                text={
                    "format": {
                        "type": "json_schema",
                        "name": EXTRACTION_SCHEMA_NAME,
                        "strict": True,
                        "schema": EXTRACTION_JSON_SCHEMA,
                    }
                },
            )
        except Exception as exc:
            if self._is_provider_error(exc):
                raise LLMExtractionUnavailable(
                    "OpenAI extraction is temporarily unavailable"
                ) from exc
            raise
        try:
            payload = json.loads(response.output_text)
        except (TypeError, json.JSONDecodeError) as exc:
            raise LLMExtractionError("Model returned invalid structured output") from exc
        if not isinstance(payload, dict):
            raise LLMExtractionError("Model returned a non-object structured output")
        return payload

    @staticmethod
    def _is_provider_error(exc: Exception) -> bool:
        if isinstance(exc, TimeoutError):
            return True
        if getattr(exc, "status_code", 0) >= 500:
            return True
        try:
            from openai import APIConnectionError, APITimeoutError, RateLimitError
        except ImportError:
            return False
        return isinstance(exc, (APIConnectionError, APITimeoutError, RateLimitError))

    def _create_client(self) -> Any:
        if not self.settings.openai_api_key:
            raise LLMExtractionError("OPENAI_API_KEY is not configured")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LLMExtractionError("OpenAI SDK is not installed") from exc
        return OpenAI(
            api_key=self.settings.openai_api_key,
            timeout=self.settings.openai_timeout_seconds,
            max_retries=self.settings.openai_max_retries,
        )
