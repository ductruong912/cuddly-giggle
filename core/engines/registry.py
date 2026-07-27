from __future__ import annotations

from config.config import Settings
from core.engines.base import ParseEngine
from core.engines.paddle import PaddleOCRVLEngine


def create_engine(name: str, app_settings: Settings) -> ParseEngine:
    """Instantiate a parse engine by its configured name.

    Keeps primary OCR engine selection driven by OCR_PRIMARY_ENGINE.
    """
    key = (name or "").strip().lower()
    if key == PaddleOCRVLEngine.name:
        return PaddleOCRVLEngine(app_settings=app_settings)
    raise ValueError(
        f"Unknown OCR engine '{name}'. Supported engines: "
        f"{PaddleOCRVLEngine.name}."
    )
