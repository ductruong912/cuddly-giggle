"""OpenAI Structured Outputs adapter for normalized OCR results."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_GPT5_REASONING_EFFORTS = {"minimal", "low", "medium", "high"}

from app.core.config import Settings, settings
from app.core.pipeline_logging import pipeline_message
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

        kwargs = {
            "model": self.settings.openai_model,
            "instructions": EXTRACTION_INSTRUCTIONS,
            "input": f"<document>\n{markdown}\n</document>",
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": EXTRACTION_SCHEMA_NAME,
                    "strict": True,
                    "schema": EXTRACTION_JSON_SCHEMA,
                }
            },
        }
        self._apply_reasoning_effort(kwargs)

        # Reasoning models (like o1, o3, gpt-5) do not support setting temperature or top_p.
        model_name = self.settings.openai_model.lower()
        if not any(prefix in model_name for prefix in ("o1", "o3", "gpt-5")):
            kwargs["temperature"] = 0.0
            kwargs["top_p"] = 0.0

        start_time = time.perf_counter()
        logger.info(
            pipeline_message("PHASE 3", "llm started model=%s input_chars=%s"),
            self.settings.openai_model,
            len(markdown),
        )
        try:
            response = self.client.responses.create(**kwargs)
            elapsed = time.perf_counter() - start_time
            logger.info(pipeline_message("PHASE 3", "llm completed duration=%.3fs"), elapsed)
            self._log_usage(response)
        except Exception as exc:
            elapsed = time.perf_counter() - start_time
            logger.error(
                pipeline_message("PHASE 3", "llm failed duration=%.3fs"),
                elapsed,
                exc_info=True,
            )
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

    def _apply_reasoning_effort(self, kwargs: dict[str, Any]) -> None:
        effort = self.settings.llm_reasoning_effort
        if not effort:
            return
        if effort not in _GPT5_REASONING_EFFORTS:
            raise LLMExtractionError(
                "Invalid LLM_REASONING_EFFORT; use minimal, low, medium, high, or leave it empty"
            )
        if "gpt-5" not in self.settings.openai_model.lower():
            raise LLMExtractionError(
                "LLM_REASONING_EFFORT is only configured for GPT-5-family models"
            )
        kwargs["reasoning"] = {"effort": effort}

    @staticmethod
    def _log_usage(response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        input_details = getattr(usage, "input_tokens_details", None)
        output_details = getattr(usage, "output_tokens_details", None)
        logger.info(
            pipeline_message(
                "PHASE 3",
                "llm usage input_tokens=%s cached_input_tokens=%s output_tokens=%s reasoning_tokens=%s",
            ),
            getattr(usage, "input_tokens", "unavailable"),
            getattr(input_details, "cached_tokens", "unavailable"),
            getattr(usage, "output_tokens", "unavailable"),
            getattr(output_details, "reasoning_tokens", "unavailable"),
        )

    @staticmethod
    def _is_provider_error(exc: Exception) -> bool:
        if isinstance(exc, TimeoutError):
            return True
        if getattr(exc, "status_code", 0) >= 500:
            return True
        try:
            # pyrefly: ignore [missing-import]
            from openai import APIConnectionError, APITimeoutError, RateLimitError
        except ImportError:
            return False
        return isinstance(exc, (APIConnectionError, APITimeoutError, RateLimitError))

    def _create_client(self) -> Any:
        if not self.settings.openai_api_key:
            raise LLMExtractionError("OPENAI_API_KEY is not configured")
        try:
            # pyrefly: ignore [missing-import]
            from openai import OpenAI
        except ImportError as exc:
            raise LLMExtractionError("OpenAI SDK is not installed") from exc
        return OpenAI(
            api_key=self.settings.openai_api_key,
            timeout=self.settings.openai_timeout_seconds,
            max_retries=self.settings.openai_max_retries,
        )
