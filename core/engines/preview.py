"""Opt-in UI metadata from live OCR results; never changes recognition or bbox values."""
from __future__ import annotations

import base64
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from io import BytesIO
import logging
import math

from core.domain.schemas import OriginalPageGeometry, PageGeometry, PageParseResult

logger = logging.getLogger(__name__)


@dataclass
class PreviewBudget:
    remaining: int
    max_edge: int


_budget: ContextVar[PreviewBudget | None] = ContextVar("ocr_ui_preview", default=None)


def preview_capture_enabled() -> bool:
    """Whether this OCR worker serves an opt-in UI request."""
    return _budget.get() is not None


@contextmanager
def capture_preview_context(max_bytes: int, max_edge: int) -> Iterator[None]:
    """Enable bounded preview capture for this worker only, including all PDF pages."""
    token = _budget.set(PreviewBudget(max_bytes, max_edge))
    try:
        yield
    finally:
        _budget.reset(token)


def attach_page_previews(
    pages: list[PageParseResult], output: object, *, input_matches_original: bool,
) -> None:
    """Capture actual OCR image extent and exact rotation mapping when available.

    Unwarping is nonlinear and Paddle does not expose its inverse map. In that
    case retain the OCR image as a separate, explicitly labelled preview.
    """
    budget = _budget.get()
    if budget is None:
        return
    if isinstance(output, Mapping):
        root = output.get("res", output)
        items = root.get("pages", [root]) if isinstance(root, Mapping) else []
    elif isinstance(output, Sequence):
        items = output
    else:
        return
    for page, item in zip(pages, items):
        if not isinstance(item, Mapping):
            continue
        item = item.get("res", item)
        if not isinstance(item, Mapping):
            continue
        pp = item.get("doc_preprocessor_res")
        if not isinstance(pp, Mapping):
            continue
        image = pp.get("output_img")
        shape = getattr(image, "shape", ())
        if len(shape) != 3 or shape[2] != 3 or min(shape[:2]) <= 0:
            continue
        geometry = PageGeometry(width=int(shape[1]), height=int(shape[0]), coordinate_space="processed")
        pipeline_settings = item.get("model_settings", {})
        if (input_matches_original and isinstance(pipeline_settings, Mapping)
                and pipeline_settings.get("use_doc_preprocessor") is False):
            geometry.coordinate_space = "original"
        original = pp.get("input_img")
        original_shape = getattr(original, "shape", ())
        model_settings = pp.get("model_settings", {})
        # Require explicit no-unwarping metadata, not a config assumption.
        if (input_matches_original and len(original_shape) >= 2
                and isinstance(model_settings, Mapping)
                and model_settings.get("use_doc_unwarping") is False):
            angle = pp.get("angle")
            if angle == -1 and model_settings.get("use_doc_orientation_classify") is False:
                angle = 0
            if angle in (0, 90, 180, 270):
                width, height = int(original_shape[1]), int(original_shape[0])
                expected = (height, width) if angle in (90, 270) else (width, height)
                if (geometry.width, geometry.height) == expected:
                    c, s = round(math.cos(math.radians(angle))), round(math.sin(math.radians(angle)))
                    # Invert Paddle's expanded-canvas rotation about the image centre.
                    tx = geometry.width / 2 - c * width / 2 - s * height / 2
                    ty = geometry.height / 2 + s * width / 2 - c * height / 2
                    geometry.original = OriginalPageGeometry(
                        width=width, height=height,
                        transform=(c, -s, -c * tx + s * ty, s, c, -s * tx - c * ty),
                    )
                    if angle == 0:
                        geometry.coordinate_space = "original"
        page.geometry = geometry
        # Only a genuinely processed page needs an image payload. Size is bounded
        # per response, and captures are never written to disk or logged.
        if geometry.coordinate_space == "processed" and budget.remaining > 0:
            try:
                from PIL import Image

                preview = Image.fromarray(image[:, :, ::-1])  # Paddle stores BGR.
                preview.thumbnail((budget.max_edge, budget.max_edge))
                buffer = BytesIO()
                preview.save(buffer, format="JPEG", quality=85)
                encoded = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
                if len(encoded) <= budget.remaining:
                    page.preview_image = encoded
                    budget.remaining -= len(encoded)
            except (ImportError, OSError, TypeError, ValueError):
                logger.warning("OCR preview unavailable for page=%s", page.page_index, exc_info=True)
