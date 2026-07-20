from __future__ import annotations

# pyrefly: ignore [missing-import]
from fastapi import FastAPI

from api.routes import doc_router, health_router
from config.config import configure_app_logging, configure_third_party_logging


def create_app() -> FastAPI:
    configure_app_logging()
    configure_third_party_logging()
    application = FastAPI(title="Vietnamese Document OCR & Extraction API", version="0.1.0")
    application.include_router(health_router)
    application.include_router(doc_router)
    return application


app = create_app()
