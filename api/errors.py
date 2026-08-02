"""Request-level error types and the single place they map to HTTP responses.

Every route used to repeat the same try/except ladder around the extraction
calls. The handlers registered here replace that duplication: routes and services
raise a domain error, and the mapping to a status code lives once.
"""
from __future__ import annotations

import logging

# pyrefly: ignore [missing-import]
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from services.concurrency import StageSaturated, StageTimedOut
from services.document_extraction import DocumentExtractionFailed
from services.llm_extraction import (
    LLMExtractionError,
    LLMExtractionInputTooLarge,
    LLMExtractionUnavailable,
)
from services.orchestrator import DocumentTooLarge


logger = logging.getLogger(__name__)


# =====================================================================================
# Request errors raised by the API layer
# =====================================================================================

class RequestError(Exception):
    """A malformed or unsupported request; carries the status code to return."""

    status_code = 400


class MissingUpload(RequestError):
    """The multipart body did not contain a usable 'file' field."""


class UnsupportedUploadType(RequestError):
    """The uploaded filename has a suffix this route does not handle."""


class InvalidRequestPayload(RequestError):
    """The request body could not be decoded into the expected shape."""


class UnsupportedContentType(RequestError):
    """The request Content-Type is not one this route accepts."""

    status_code = 415


class UploadTooLarge(RequestError):
    """The upload exceeds MAX_UPLOAD_BYTES."""

    status_code = 413


# =====================================================================================
# Handler registration
# =====================================================================================

def _json_error(status_code: int, detail: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail}, headers=headers)


def register_exception_handlers(application: FastAPI) -> None:
    """Map domain and request errors to HTTP responses for every route at once.

    Starlette resolves handlers along the exception's MRO, so the subclasses
    registered here win over their more general base classes.
    """

    @application.exception_handler(RequestError)
    async def _handle_request_error(_: Request, exc: RequestError) -> JSONResponse:
        return _json_error(exc.status_code, str(exc))

    @application.exception_handler(StageSaturated)
    async def _handle_stage_saturated(_: Request, exc: StageSaturated) -> JSONResponse:
        return _json_error(
            503,
            str(exc),
            headers={"Retry-After": str(max(1, int(exc.wait_timeout_seconds)))},
        )

    @application.exception_handler(StageTimedOut)
    async def _handle_stage_timeout(_: Request, exc: StageTimedOut) -> JSONResponse:
        # 504, not 503: the dependency accepted the work and never finished it.
        # The stage limiter has already logged that the slot is still held.
        return _json_error(504, str(exc))

    @application.exception_handler(LLMExtractionInputTooLarge)
    async def _handle_input_too_large(_: Request, exc: LLMExtractionInputTooLarge) -> JSONResponse:
        return _json_error(413, str(exc))

    @application.exception_handler(DocumentTooLarge)
    async def _handle_document_too_large(_: Request, exc: DocumentTooLarge) -> JSONResponse:
        return _json_error(413, str(exc))

    @application.exception_handler(LLMExtractionUnavailable)
    async def _handle_llm_unavailable(_: Request, exc: LLMExtractionUnavailable) -> JSONResponse:
        return _json_error(503, str(exc))

    @application.exception_handler(LLMExtractionError)
    async def _handle_llm_error(_: Request, exc: LLMExtractionError) -> JSONResponse:
        return _json_error(422, str(exc))

    @application.exception_handler(DocumentExtractionFailed)
    async def _handle_pipeline_failure(_: Request, exc: DocumentExtractionFailed) -> JSONResponse:
        # The service already logged the traceback at the point of failure.
        return _json_error(500, str(exc))

    @application.exception_handler(RuntimeError)
    async def _handle_runtime_error(_: Request, exc: RuntimeError) -> JSONResponse:
        # Engines and model-asset checks signal "this dependency is not usable
        # right now" with a plain RuntimeError; that is a 503, not a 500.
        logger.error("dependency unavailable: %s", exc, exc_info=True)
        return _json_error(503, str(exc))
