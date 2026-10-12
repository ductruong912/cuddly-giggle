"""Turn loosely-typed engine payloads into the shapes the rest of the code expects.

Engine output arrives as dicts, result objects, numpy scalars and occasionally
JSON strings; everything here is defensive by design and never raises.
"""
from __future__ import annotations

from collections.abc import Iterable
import json
import uuid

from core.domain.schemas import BlockType, Point
from core.engines.normalizer.markdown_text import extract_markdown


def safe_float(value: object, default: float = 0.0) -> float:
    """Coerce to float, falling back to ``default`` for anything unparseable."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: object, default: int = 0) -> int:
    """Coerce to int, falling back to ``default`` for anything unparseable."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def map_label_to_type(label: str | None) -> BlockType:
    """Map an engine's free-form layout label onto the internal block type."""
    key = (label or "").strip().lower()
    if "table" in key:
        return BlockType.table
    if "formula" in key or "equation" in key:
        return BlockType.formula
    if "chart" in key or "figure" in key:
        return BlockType.chart
    if "seal" in key or "stamp" in key:
        return BlockType.seal
    if "title" in key:
        return BlockType.title
    if any(token in key for token in ["text", "paragraph", "line", "word"]):
        return BlockType.text
    return BlockType.other


def to_polygon(raw_coordinate: object) -> list[Point]:
    """Accept either an [x1,y1,x2,y2] box or a point list, and return a polygon."""
    if callable(getattr(raw_coordinate, "tolist", None)):
        raw_coordinate = raw_coordinate.tolist()
    if not isinstance(raw_coordinate, (list, tuple)):
        return []

    if len(raw_coordinate) == 4 and all(isinstance(v, (int, float)) for v in raw_coordinate):
        x1, y1, x2, y2 = raw_coordinate
        return [
            Point(x=float(x1), y=float(y1)),
            Point(x=float(x2), y=float(y1)),
            Point(x=float(x2), y=float(y2)),
            Point(x=float(x1), y=float(y2)),
        ]

    points: list[Point] = []
    for item in raw_coordinate:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            points.append(Point(x=safe_float(item[0]), y=safe_float(item[1])))
    return points


def bbox_to_polygon(bbox: object) -> list[Point]:
    """Convert a 4-number bounding box into a four-point polygon."""
    if callable(getattr(bbox, "tolist", None)):
        bbox = bbox.tolist()
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4 and all(isinstance(v, (int, float)) for v in bbox[:4]):
        x1, y1, x2, y2 = bbox[:4]
        return [
            Point(x=float(x1), y=float(y1)),
            Point(x=float(x2), y=float(y1)),
            Point(x=float(x2), y=float(y2)),
            Point(x=float(x1), y=float(y2)),
        ]
    return []


def centroid(poly: list[Point]) -> tuple[float, float]:
    """Mean point of a polygon; (0, 0) when it has no points."""
    if not poly:
        return (0.0, 0.0)
    x = sum(p.x for p in poly) / len(poly)
    y = sum(p.y for p in poly) / len(poly)
    return (x, y)


def new_block_id(prefix: str) -> str:
    """Generate an id for a block or table the engine did not name."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def avg_positive(values: Iterable[float]) -> float:
    """Mean of the values above zero; 0.0 when there are none."""
    positives = [v for v in values if v > 0.0]
    if not positives:
        return 0.0
    return sum(positives) / len(positives)


def object_to_dict(item: object) -> dict:
    """Best-effort conversion of a result item to a plain dict."""
    if isinstance(item, dict):
        return item
    if hasattr(item, "to_dict") and callable(getattr(item, "to_dict")):
        try:
            value = item.to_dict()
            if isinstance(value, dict):
                return value
        except Exception:
            pass
    if hasattr(item, "__dict__"):
        try:
            return dict(vars(item))
        except Exception:
            return {}
    return {}


def normalize_parsing_item(item: object) -> dict:
    """Flatten one ``parsing_res_list`` entry onto a stable set of keys."""
    d = object_to_dict(item)
    if not d:
        return {}
    return {
        "label": d.get("block_label", d.get("label", d.get("type", ""))),
        "content": d.get("block_content", d.get("content", d.get("text", ""))),
        "bbox": d.get("block_bbox", d.get("bbox")),
        "polygon_points": d.get("block_polygon_points", d.get("polygon_points")),
        "block_id": d.get("block_id", d.get("id")),
        "block_order": d.get("block_order", d.get("order")),
        "group_id": d.get("group_id"),
        "score": d.get("score"),
        "raw": d,
    }


def result_to_dict(raw: object) -> dict:
    """Convert an engine result (dict, ``.json`` provider, or object) to a dict."""
    # Paddle result classes inherit dict but expose the complete schema via .json.
    try:
        json_attr = getattr(raw, "json", None)
        value = json_attr() if callable(json_attr) else json_attr
    except Exception:
        value = None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = None
    if isinstance(value, dict):
        raw = value

    if isinstance(raw, dict):
        converted = dict(raw)
        if "res" in converted and not isinstance(converted["res"], (list, str, int, float, bool, type(None))):
            nested = result_to_dict(converted["res"])
            if nested:
                converted["res"] = nested.get("res", nested)
        if "pages" in converted and isinstance(converted["pages"], list):
            pages: list[object] = converted["pages"]
            converted["pages"] = [
                result_to_dict(page)
                for page in pages
            ]
        if "markdown" in converted and isinstance(converted["markdown"], dict):
            md_text = extract_markdown(converted["markdown"])
            if md_text:
                converted["markdown"] = md_text
        return converted
    if hasattr(raw, "__dict__"):
        return dict(vars(raw))
    return {}
