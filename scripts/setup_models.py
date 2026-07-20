"""Download only the OCR model profiles explicitly requested by the operator."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.config import settings  # noqa: E402
from core.engines.fast_paddle import PaddleOCRFastEngine  # noqa: E402
from core.engines.registry import create_engine  # noqa: E402
from services.model_assets import write_model_profile  # noqa: E402


_PROFILES = ("fast-onnx", "paddleocr-vl", "pp-structure-v3")


def _warm(profile: str) -> None:
    if profile == "fast-onnx":
        PaddleOCRFastEngine(settings).warmup()
    else:
        engine = create_engine(profile.replace("-", "_"), settings)
        engine.warmup()
    write_model_profile(settings, profile)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast-onnx", action="store_true", help="Download Fast OCR ONNX models.")
    parser.add_argument("--paddleocr-vl", action="store_true", help="Download PaddleOCR-VL models.")
    parser.add_argument("--pp-structure-v3", action="store_true", help="Download PP-StructureV3 models.")
    args = parser.parse_args(argv)
    selected = [profile for profile in _PROFILES if getattr(args, profile.replace("-", "_"))]
    if not selected:
        parser.error("select at least one model profile")
    os.environ["CUDDLY_GIGGLE_MODEL_SETUP"] = "1"
    try:
        for profile in selected:
            _warm(profile)
            print(f"prepared: {profile}")
    finally:
        os.environ.pop("CUDDLY_GIGGLE_MODEL_SETUP", None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
