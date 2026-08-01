"""FastAPI application factory and process lifespan."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

# pyrefly: ignore [missing-import]
from fastapi import FastAPI
# pyrefly: ignore [missing-import]
from slowapi import _rate_limit_exceeded_handler
# pyrefly: ignore [missing-import]
from slowapi.errors import RateLimitExceeded
# pyrefly: ignore [missing-import]
from slowapi.middleware import SlowAPIMiddleware

from api.dependencies import get_pipeline_limiters, warmup_primary_engine
from api.errors import register_exception_handlers
from api.rate_limit import limiter
from api.routes import doc_router, health_router, ocr_router
from api.uploads import cleanup_temp_dir
from config.config import configure_app_logging, configure_third_party_logging, settings
from services.concurrency import apply_thread_pool_size
from services.local_ocr_selector import log_gpu_availability
from services.vl_runtime import build_vl_runtime_manager


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Size the worker pool, clear stale temp files, and own the VL runtime process."""
    apply_thread_pool_size(settings)
    get_pipeline_limiters()
    cleanup_temp_dir(settings)
    runtime_manager = build_vl_runtime_manager(warmup=warmup_primary_engine)
    application.state.vl_runtime_manager = runtime_manager
    try:
        yield
    finally:
        runtime_manager.shutdown()


def create_app() -> FastAPI:
    """Build the ASGI application. Safe to use as `uvicorn api.application:app`."""
    configure_app_logging()
    configure_third_party_logging()
    log_gpu_availability()
    application = FastAPI(
        title="Vietnamese Document OCR & Extraction API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.limiter = limiter
    application.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    application.add_middleware(SlowAPIMiddleware)
    register_exception_handlers(application)
    application.include_router(health_router)
    application.include_router(doc_router)
    application.include_router(ocr_router)
    return application


app = create_app()
