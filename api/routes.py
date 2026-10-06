"""HTTP routes. Request translation only — the pipeline lives in the service layer.

Note: no ``from __future__ import annotations`` here. FastAPI resolves handler
signatures at import time and cannot build a field from a stringified
``UploadFile | None``.
"""
import logging

# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

from api.dependencies import (
    ensure_gpu_gguf_runtime,
    get_database_pool,
    get_local_extraction_service,
    get_orchestrator,
    get_pipeline_limiters,
    get_upload_stager,
    require_extraction_store,
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
from config.pipeline_logging import pipeline_message, source_document_context
from core.domain.schemas import LLMExtractionResponse, UIConfigResponse
from services.concurrency import PipelineLimiters
from services.document_extraction import DocumentExtractionService
from services.local_ocr_selector import has_usable_gpu
from services.persistence import ExtractionQuery, ExtractionStore
from services.persistence.extraction_store import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from services.orchestrator import ParseOrchestrator
from services.output import save_parse_artifacts


logger = logging.getLogger(__name__)

SUPPORTED_INPUT_SUFFIXES = frozenset(
    {
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".xlsm",
        ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff",
    }
)
_MARKDOWN_BODY_CONTENT_TYPES = ("text/markdown", "text/plain", "application/json")

_LOCAL_UNSUPPORTED_MESSAGE = (
    "Unsupported input type. Use PDF, Word, Excel, Markdown, or image files."
)
# =====================================================================================
# Health
# =====================================================================================

health_router = APIRouter(tags=["health"])
ui_router = APIRouter(prefix="/v1/ui", tags=["ui"])


@ui_router.get("/config", response_model=UIConfigResponse)
def ui_config() -> UIConfigResponse:
    """Expose the existing OCR upload limits to the browser."""
    return UIConfigResponse(
        supported_suffixes=sorted(SUPPORTED_INPUT_SUFFIXES),
        max_upload_bytes=settings.max_upload_bytes,
        pdf_max_pages=settings.pdf_max_pages,
    )


@health_router.get("/healthz")
def healthz(limiters: PipelineLimiters = Depends(get_pipeline_limiters)) -> dict[str, object]:
    """Liveness: the process is up and serving. Never fails on a sick dependency.

    This is what the container healthcheck watches, so it must not report a
    stalled backend as a dead application — that would restart the API in a loop
    while leaving the actual problem untouched. Use ``/readyz`` for that.
    """
    return {"status": "ok", "stages": limiters.snapshot()}


@health_router.get("/readyz")
def readyz(
    request: Request,
    limiters: PipelineLimiters = Depends(get_pipeline_limiters),
) -> JSONResponse:
    """Readiness: whether this instance can actually serve work right now.

    Returns 503 when a dependency is down or a stage is running below capacity,
    so a load balancer stops sending traffic here instead of collecting failures.
    """
    checks = {
        "vl_runtime": _vl_runtime_state(request),
        "llm_credentials": "ok" if settings.openai_api_key else "missing",
        "stages": "ok" if not limiters.degraded_stages else "degraded",
        "database": _database_state(),
    }
    degraded = limiters.degraded_stages
    ready = all(state == "ok" for state in checks.values())
    payload: dict[str, object] = {
        "status": "ready" if ready else "not_ready",
        "checks": checks,
        "stages": limiters.snapshot(),
    }
    if degraded:
        # A stage below capacity means work timed out and never came back; the
        # slots return only when the wedged dependency is restarted.
        payload["degraded_stages"] = degraded
        logger.warning("readiness degraded: stages holding abandoned slots: %s", degraded)
    return JSONResponse(status_code=200 if ready else 503, content=payload)


def _database_state() -> str:
    """Whether the history database can serve a query, or is not configured at all."""
    if not settings.persistence_enabled:
        return "ok"
    return "ok" if get_database_pool().check() else "down"


def _vl_runtime_state(request: Request) -> str:
    """Whether the local VL backend is usable, or why the question does not apply."""
    if not (settings.paddleocr_vl_use_gguf and has_usable_gpu()):
        return "ok"
    manager = getattr(request.app.state, "vl_runtime_manager", None)
    if manager is None:
        return "unconfigured"
    # Not yet started is fine: the runtime is prepared on first use by design.
    return "ok" if (not manager.was_started or manager.is_ready) else "down"


# =====================================================================================
# Documents
# =====================================================================================

doc_router = APIRouter(prefix="/v1/extract", tags=["documents"])
ocr_router = APIRouter(prefix="/v1/doc", tags=["documents"])


# =====================================================================================
# History
# =====================================================================================

history_router = APIRouter(prefix="/v1/extractions", tags=["history"])


@history_router.get("")
def list_extractions(
    po_number: str | None = Query(default=None, description="Exact purchase order number."),
    status: str | None = Query(
        default=None, description="Filter by validation status: valid or needs_review."
    ),
    toto_number: str | None = Query(
        default=None, description="Only orders containing this item code."
    ),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    store: ExtractionStore = Depends(require_extraction_store),
) -> dict[str, object]:
    """List past extractions, newest first."""
    query = ExtractionQuery(
        po_number=po_number,
        validation_status=status,
        toto_number=toto_number,
        limit=limit,
        offset=offset,
    )
    return {
        "total": store.count(query),
        "limit": limit,
        "offset": offset,
        "items": store.list(query),
    }


@history_router.get("/{request_id}")
def get_extraction(
    request_id: str,
    store: ExtractionStore = Depends(require_extraction_store),
) -> dict[str, object]:
    """Fetch one past extraction and its line items."""
    record = store.get(request_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No extraction for request_id {request_id}")
    return record


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
        with source_document_context(staged.filename):
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
