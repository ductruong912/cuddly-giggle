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
from core.engines.paddle import PaddleOCRVLEngine  # noqa: E402
from core.engines.paddle_fast import PaddleOCRFastEngine  # noqa: E402
from services.local_ocr_selector import has_usable_gpu  # noqa: E402
from services.model_assets import write_model_profile  # noqa: E402


_PROFILES = ("fast-onnx", "paddleocr-vl")


def _warm(profile: str) -> None:
    if profile == "fast-onnx":
        PaddleOCRFastEngine(settings).warmup()
    else:
        PaddleOCRVLEngine(settings).warmup()
    write_model_profile(settings, profile)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--auto", action="store_true",
        help="Prepare the profile selected by the API's hardware check.",
    )
    parser.add_argument("--fast-onnx", action="store_true", help="Download Fast OCR ONNX models.")
    parser.add_argument("--paddleocr-vl", action="store_true", help="Download PaddleOCR-VL models.")
    args = parser.parse_args(argv)
    selected = [profile for profile in _PROFILES if getattr(args, profile.replace("-", "_"))]
    if args.auto:
        if selected:
            parser.error("--auto cannot be combined with explicit model profiles")
        selected = ["paddleocr-vl" if has_usable_gpu() else "fast-onnx"]
    if not selected:
        parser.error("select at least one model profile")
    previous_setup_mode = os.environ.get("CUDDLY_GIGGLE_MODEL_SETUP")
    os.environ["CUDDLY_GIGGLE_MODEL_SETUP"] = "1"
    try:
        for profile in selected:
            _warm(profile)
            print(f"prepared: {profile}")
    finally:
        if previous_setup_mode is None:
            os.environ.pop("CUDDLY_GIGGLE_MODEL_SETUP", None)
        else:
            os.environ["CUDDLY_GIGGLE_MODEL_SETUP"] = previous_setup_mode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
