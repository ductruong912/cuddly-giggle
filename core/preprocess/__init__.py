"""Opt-in image preprocessing applied to page images before OCR.

``chain`` is importable without OpenCV installed; the operators in ``image_ops``
are imported lazily so a deployment without cv2 degrades to a no-op rather than
failing at import time.
"""
from __future__ import annotations

from core.preprocess.chain import PreprocessResult, StepTiming, preprocess_file


__all__ = ["PreprocessResult", "StepTiming", "preprocess_file"]
