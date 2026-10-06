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

from api.dependencies import get_database_pool, get_pipeline_limiters, warmup_primary_engine
from api.errors import register_exception_handlers
from api.frontend import register_frontend
from api.rate_limit import limiter
from api.routes import doc_router, health_router, history_router, ocr_router, ui_router
from api.uploads import cleanup_temp_dir
from config.config import configure_app_logging, configure_third_party_logging, settings
from services.concurrency import apply_thread_pool_size
from services.local_ocr_selector import log_gpu_availability
from services.persistence import MigrationRunner
from services.retention import artifact_retention_task
from services.vl_runtime import build_vl_runtime_manager


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Size the worker pool, clear stale temp files, and own the VL runtime process."""
    apply_thread_pool_size(settings)
    get_pipeline_limiters()
    cleanup_temp_dir(settings)
    _open_database()
    runtime_manager = build_vl_runtime_manager(warmup=warmup_primary_engine)
    application.state.vl_runtime_manager = runtime_manager
    try:
        async with artifact_retention_task(settings):
            yield
    finally:
        runtime_manager.shutdown()
        get_database_pool().close()


def _open_database() -> None:
    """Open the pool and bring the schema up to date, when a database is configured.

    Startup fails loudly on an unreachable database rather than deferring the
    error to the first upload — a service that cannot record its results should
    not accept them.
    """
    if not settings.persistence_enabled:
        logger.info("no DATABASE_URL configured; extraction history is disabled")
        return

    pool = get_database_pool()
    pool.open()
    if settings.database_migrate_on_startup:
        MigrationRunner(pool).run()
    else:
        logger.info("DATABASE_MIGRATE_ON_STARTUP is off; assuming the schema is current")


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
    application.include_router(history_router)
    application.include_router(ui_router)
    register_frontend(application, settings)
    return application


app = create_app()
