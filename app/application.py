from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import documents, health
from app.core.config import configure_app_logging, configure_third_party_logging


def create_app() -> FastAPI:
    configure_app_logging()
    configure_third_party_logging()
    application = FastAPI(title="Vietnamese Document OCR & Extraction API", version="0.1.0")
    application.include_router(health.router)
    application.include_router(documents.router)
    return application


app = create_app()
