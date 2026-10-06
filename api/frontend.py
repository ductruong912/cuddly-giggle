"""Serve the optional OCR playground build without intercepting API routes."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config.config import Settings


def register_frontend(application: FastAPI, app_settings: Settings) -> None:
    """Register only known UI paths when a complete Vite build exists."""
    dist = Path(app_settings.frontend_dist_dir)
    index = dist / "index.html"
    assets = dist / "assets"
    if not index.is_file() or not assets.is_dir():
        return

    application.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

    @application.get("/", include_in_schema=False)
    @application.get("/playground", include_in_schema=False)
    @application.get("/playground/", include_in_schema=False)
    def playground() -> FileResponse:
        """Return the entrypoint; let the browser fetch bundled assets locally."""
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
