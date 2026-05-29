from __future__ import annotations

import os

import uvicorn

from app.api.dependencies import get_orchestrator
from app.application import app
from app.core.config import settings


def warmup_models_on_startup() -> None:
    if not settings.warmup_models_on_startup:
        return
    primary_engine = get_orchestrator().primary_engine
    warmup = getattr(primary_engine, "warmup", None)
    if not callable(warmup):
        raise RuntimeError(f"Primary engine {primary_engine.__class__.__name__} does not support warmup.")
    warmup()


def main() -> None:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    warmup_models_on_startup()
    uvicorn.run(app, host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
