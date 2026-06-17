from __future__ import annotations

from app.core.config import Settings
from app.engines.base import ParseEngine
from app.engines.paddle import PaddleOCRVLEngine, PPStructureV3Engine


def create_engine(name: str, app_settings: Settings) -> ParseEngine:
    """Instantiate a parse engine by its configured name.

    Keeps engine selection driven by OCR_PRIMARY_ENGINE / OCR_FALLBACK_ENGINE
    instead of hardcoding concrete classes in the orchestrator.
    """
    key = (name or "").strip().lower()
    if key == PaddleOCRVLEngine.name:
        return PaddleOCRVLEngine(app_settings=app_settings)
    if key == PPStructureV3Engine.name:
        return PPStructureV3Engine(app_settings=app_settings)
    raise ValueError(
        f"Unknown OCR engine '{name}'. Supported engines: "
        f"{PaddleOCRVLEngine.name}, {PPStructureV3Engine.name}."
    )
