from __future__ import annotations

# pyrefly: ignore [missing-import]
from fastapi import FastAPI
# pyrefly: ignore [missing-import]
from slowapi import _rate_limit_exceeded_handler
# pyrefly: ignore [missing-import]
from slowapi.errors import RateLimitExceeded
# pyrefly: ignore [missing-import]
from slowapi.middleware import SlowAPIMiddleware

from api.rate_limit import limiter
from api.routes import doc_router, health_router, ocr_router
from config.config import configure_app_logging, configure_third_party_logging
from services.local_ocr_selector import log_gpu_availability


def create_app() -> FastAPI:
    configure_app_logging()
    configure_third_party_logging()
    log_gpu_availability()
    application = FastAPI(title="Vietnamese Document OCR & Extraction API", version="0.1.0")
    application.state.limiter = limiter
    application.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    application.add_middleware(SlowAPIMiddleware)
    application.include_router(health_router)
    application.include_router(doc_router)
    application.include_router(ocr_router)
    return application


app = create_app()
