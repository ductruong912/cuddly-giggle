"""Normalize adapter-specific engine output into the internal page schema.

The work splits into four concerns: coercing loose payloads into known shapes
(``coercion``), locating and tidying Markdown (``markdown_text``), recovering
table cells (``tables``), and building ordered page blocks (``blocks``).
``pipeline`` composes them.
"""
from __future__ import annotations

from core.engines.normalizer.coercion import map_label_to_type, to_polygon
from core.engines.normalizer.pipeline import normalize_engine_output


__all__ = ["map_label_to_type", "normalize_engine_output", "to_polygon"]
