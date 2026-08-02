"""Shared, process-wide dependencies for the routes.

Everything here is expensive to build (model pipelines, HTTP clients, semaphores)
and must exist exactly once per process, so construction is guarded by a lock
rather than left to ``lru_cache``, which can race two callers into building two
pipelines on a cold start.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, TypeVar

# pyrefly: ignore [missing-import]
from fastapi import HTTPException, Request

from api.uploads import UploadStager
from config.config import settings
from services.concurrency import PipelineLimiters
from services.document_extraction import DocumentExtractionService
from services.llm_extraction import LLMExtractionService
from services.local_ocr_selector import has_usable_gpu
from services.online_orchestrator import OnlineParseOrchestrator
from services.orchestrator import ParseOrchestrator
from services.persistence import DatabasePool, ExtractionStore
from services.vl_runtime import VLRuntimeManager


logger = logging.getLogger(__name__)

T = TypeVar("T")

_singletons: dict[str, object] = {}
# Reentrant: the composite factories below build their own dependencies through
# this same helper, so the constructing thread must be able to re-enter the lock.
_singleton_lock = threading.RLock()


def _singleton(key: str, factory: Callable[[], T]) -> T:
    """Build ``factory()`` at most once per process, even under concurrent first calls."""
    existing = _singletons.get(key)
    if existing is not None:
        return existing  # type: ignore[return-value]
    with _singleton_lock:
        cached = _singletons.get(key)
        if cached is None:
            cached = factory()
            _singletons[key] = cached
        return cached  # type: ignore[return-value]


# =====================================================================================
# Pipeline components
# =====================================================================================

def get_pipeline_limiters() -> PipelineLimiters:
    """Bounded stage semaphores shared by every request."""
    return _singleton("limiters", lambda: PipelineLimiters(settings))


def get_upload_stager() -> UploadStager:
    """Writer that streams uploads to the temp directory under the size cap."""
    return _singleton("stager", lambda: UploadStager(get_pipeline_limiters().io, settings))


def get_orchestrator() -> ParseOrchestrator:
    """Local parse orchestrator, holding the loaded OCR pipeline."""
    return _singleton("orchestrator", ParseOrchestrator)


def get_online_orchestrator() -> OnlineParseOrchestrator:
    """DataLab-backed parse orchestrator."""
    return _singleton("online_orchestrator", OnlineParseOrchestrator)


def get_llm_extractor() -> LLMExtractionService:
    """Structured-output extraction client, reused across requests."""
    return _singleton("llm_extractor", LLMExtractionService)


def get_database_pool() -> DatabasePool:
    """The process-wide connection pool. Opened by the application lifespan."""
    return _singleton("database_pool", lambda: DatabasePool(settings))


def get_extraction_store() -> ExtractionStore | None:
    """History store, or ``None`` when no database is configured."""
    if not settings.persistence_enabled:
        return None
    return _singleton("extraction_store", lambda: ExtractionStore(get_database_pool()))


def require_extraction_store() -> ExtractionStore:
    """The history store for routes that cannot work without one.

    Raises:
        HTTPException: 503 when the service is running without a database.
    """
    store = get_extraction_store()
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="Extraction history is unavailable: no DATABASE_URL is configured.",
        )
    return store


def get_local_extraction_service() -> DocumentExtractionService:
    """Full pipeline for the local OCR route."""
    return _singleton(
        "local_extraction",
        lambda: DocumentExtractionService(
            get_orchestrator(),
            get_llm_extractor(),
            get_pipeline_limiters(),
            route_label="local",
            app_settings=settings,
            store=get_extraction_store(),
        ),
    )


def get_online_extraction_service() -> DocumentExtractionService:
    """Full pipeline for the online DataLab route."""
    return _singleton(
        "online_extraction",
        lambda: DocumentExtractionService(
            get_online_orchestrator(),
            get_llm_extractor(),
            get_pipeline_limiters(),
            route_label="online",
            app_settings=settings,
            store=get_extraction_store(),
        ),
    )


# =====================================================================================
# GPU runtime
# =====================================================================================

def get_vl_runtime_manager(request: Request) -> VLRuntimeManager:
    """The llama.cpp lifecycle manager attached to the app during startup."""
    manager = getattr(request.app.state, "vl_runtime_manager", None)
    if manager is None:
        raise RuntimeError("VL runtime manager is not configured")
    return manager


def ensure_gpu_gguf_runtime(request: Request) -> None:
    """Start llama.cpp on first use, only when the local GPU route needs the GGUF VLM."""
    if not (has_usable_gpu() and settings.paddleocr_vl_use_gguf):
        return
    try:
        get_vl_runtime_manager(request).ensure_ready()
    except Exception as exc:
        logger.exception("VL GGUF runtime could not be prepared")
        raise HTTPException(status_code=503, detail=f"VL GGUF runtime is unavailable: {exc}") from exc


def warmup_primary_engine() -> None:
    """Load the local OCR pipeline ahead of the first request, when configured to."""
    if not settings.warmup_models_on_startup:
        return
    primary_engine = get_orchestrator().primary_engine
    warmup = getattr(primary_engine, "warmup", None)
    if not callable(warmup):
        raise RuntimeError(
            f"Primary engine {primary_engine.__class__.__name__} does not support warmup."
        )
    logger.info("warming up primary engine %s", primary_engine.name)
    warmup()


def reset_singletons() -> None:
    """Drop every cached component. Intended for tests, not request handling."""
    with _singleton_lock:
        _singletons.clear()
