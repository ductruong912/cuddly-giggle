"""HTTP routes. Request translation only — the pipeline lives in the service layer.

Note: no ``from __future__ import annotations`` here. FastAPI resolves handler
signatures at import time and cannot build a field from a stringified
``UploadFile | None``.
"""
import logging

# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse

from api.dependencies import (
    ensure_gpu_gguf_runtime,
    get_local_extraction_service,
    get_online_extraction_service,
    get_orchestrator,
    get_pipeline_limiters,
    get_upload_stager,
)
from api.errors import UnsupportedContentType
from api.rate_limit import limiter
from api.uploads import (
    MARKDOWN_SUFFIXES,
    MULTIPART_CONTENT_TYPE,
    StagedUpload,
    UploadStager,
    read_markdown_payload,
    read_markdown_upload,
    resolve_upload,
    upload_suffix,
)
from config.config import settings
from config.pipeline_logging import pipeline_message
from core.domain.schemas import LLMExtractionResponse
from services.concurrency import PipelineLimiters
from services.document_extraction import DocumentExtractionService
from services.orchestrator import ParseOrchestrator
from services.output import save_parse_artifacts


logger = logging.getLogger(__name__)

SUPPORTED_INPUT_SUFFIXES = frozenset(
    {
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".xlsm",
        ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff",
    }
)
FAST_OCR_INPUT_SUFFIXES = frozenset(
    {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
)
_MARKDOWN_BODY_CONTENT_TYPES = ("text/markdown", "text/plain", "application/json")

_LOCAL_UNSUPPORTED_MESSAGE = (
    "Unsupported input type. Use PDF, Word, Excel, Markdown, or image files."
)
_ONLINE_UNSUPPORTED_MESSAGE = "Online OCR supports PDF and image files only."


# =====================================================================================
# Health
# =====================================================================================

health_router = APIRouter(tags=["health"])


@health_router.get("/healthz")
def healthz(limiters: PipelineLimiters = Depends(get_pipeline_limiters)) -> dict[str, object]:
    """Liveness plus current occupancy of each bounded pipeline stage."""
    return {"status": "ok", "stages": limiters.snapshot()}


# =====================================================================================
# Documents
# =====================================================================================

doc_router = APIRouter(prefix="/v1/extract", tags=["documents"])
ocr_router = APIRouter(prefix="/v1/doc", tags=["documents"])


@doc_router.post("/local", response_model=LLMExtractionResponse)
@limiter.limit(settings.rate_limit_extract)
async def extract_local_document(
    request: Request,
    file: UploadFile | None = File(None),
    service: DocumentExtractionService = Depends(get_local_extraction_service),
    stager: UploadStager = Depends(get_upload_stager),
    _: None = Depends(ensure_gpu_gguf_runtime),
) -> LLMExtractionResponse:
    """Run local OCR plus structured extraction on an upload, or on supplied Markdown."""
    content_type = request.headers.get("content-type", "")

    if MULTIPART_CONTENT_TYPE in content_type:
        upload = await resolve_upload(request, file)
        if upload_suffix(upload) in MARKDOWN_SUFFIXES:
            markdown = await read_markdown_upload(upload)
            return await service.extract_markdown(
                markdown,
                reason="Provided parsed Markdown via file upload.",
                artifact_name=upload.filename or "extraction.json",
            )
        return await _extract_upload(
            service,
            stager,
            upload,
            allowed_suffixes=SUPPORTED_INPUT_SUFFIXES,
            unsupported_message=_LOCAL_UNSUPPORTED_MESSAGE,
        )

    if any(accepted in content_type for accepted in _MARKDOWN_BODY_CONTENT_TYPES):
        markdown = await read_markdown_payload(request)
        return await service.extract_markdown(
            markdown, reason="Provided Markdown request body."
        )

    raise UnsupportedContentType(
        "Unsupported Content-Type. Use multipart/form-data, text/markdown, "
        "text/plain, or application/json."
    )


@doc_router.post("/online", response_model=LLMExtractionResponse)
@limiter.limit(settings.rate_limit_extract)
async def extract_online_document(
    request: Request,
    file: UploadFile | None = File(None),
    service: DocumentExtractionService = Depends(get_online_extraction_service),
    stager: UploadStager = Depends(get_upload_stager),
) -> LLMExtractionResponse:
    """Run DataLab SuryaOCR plus structured extraction on an uploaded PDF or image."""
    upload = await resolve_upload(request, file)
    return await _extract_upload(
        service,
        stager,
        upload,
        allowed_suffixes=FAST_OCR_INPUT_SUFFIXES,
        unsupported_message=_ONLINE_UNSUPPORTED_MESSAGE,
    )


@ocr_router.post("/ocr", response_class=PlainTextResponse)
@limiter.limit(settings.rate_limit_extract)
async def ocr_document(
    request: Request,
    file: UploadFile | None = File(None),
    orchestrator: ParseOrchestrator = Depends(get_orchestrator),
    stager: UploadStager = Depends(get_upload_stager),
    limiters: PipelineLimiters = Depends(get_pipeline_limiters),
    _: None = Depends(ensure_gpu_gguf_runtime),
) -> PlainTextResponse:
    """Run local OCR only and return Markdown, for debugging the parse stage."""
    upload = await resolve_upload(request, file)
    staged = await stager.stage(
        upload,
        allowed_suffixes=SUPPORTED_INPUT_SUFFIXES,
        unsupported_message=_LOCAL_UNSUPPORTED_MESSAGE,
    )
    try:
        response = await limiters.ocr.run(orchestrator.parse, str(staged.path))
        await limiters.io.run(save_parse_artifacts, response, staged.filename)
        if not response.markdown:
            raise HTTPException(status_code=422, detail="No markdown output produced.")
        return PlainTextResponse(response.markdown, media_type="text/markdown")
    finally:
        stager.discard(staged)


# =====================================================================================
# Shared route helpers
# =====================================================================================

async def _extract_upload(
    service: DocumentExtractionService,
    stager: UploadStager,
    upload: UploadFile,
    *,
    allowed_suffixes: frozenset[str],
    unsupported_message: str,
) -> LLMExtractionResponse:
    """Stage an upload, run the pipeline against it, and always clean the temp file."""
    staged = await stager.stage(
        upload,
        allowed_suffixes=allowed_suffixes,
        unsupported_message=unsupported_message,
    )
    _log_received(staged)
    try:
        return await service.extract_document(staged.path, filename=staged.filename)
    finally:
        stager.discard(staged)


def _log_received(staged: StagedUpload) -> None:
    logger.info(
        pipeline_message("received file=%s suffix=%s size_bytes=%s"),
        staged.filename,
        staged.suffix,
        staged.size_bytes,
    )
