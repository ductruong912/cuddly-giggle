"""Build page blocks from the two layout shapes engines produce, and order them."""
from __future__ import annotations

from collections.abc import Iterable

from core.domain.schemas import Block
from core.engines.normalizer.coercion import (
    bbox_to_polygon,
    centroid,
    map_label_to_type,
    new_block_id,
    normalize_parsing_item,
    safe_float,
    safe_int,
    to_polygon,
)


# Blocks without a usable order sort behind every ordered block.
_NO_ORDER = 10**9


def build_blocks_from_layout_boxes(
    boxes: Iterable[dict],
    page_index: int,
    source_engine: str,
) -> list[Block]:
    """Build blocks from detection boxes (``layout_det_res``, ``boxes``, ``blocks``)."""
    blocks: list[Block] = []
    for box in boxes:
        if not isinstance(box, dict):
            continue
        label = str(box.get("label", "")).strip() or "other"
        poly = []
        for key in ("coordinate", "bbox", "box"):
            poly = to_polygon(box.get(key))
            if poly:
                break
        extra = {"label": label}
        order = box.get("block_order")
        if order is not None:
            extra["block_order"] = safe_int(order, -1)
        block = Block(
            block_id=new_block_id("blk"),
            type=map_label_to_type(label),
            content=str(box.get("text", "")).strip(),
            bbox=poly,
            confidence=safe_float(box.get("score"), 0.0),
            page_index=page_index,
            source_engine=source_engine,
            extra=extra,
        )
        blocks.append(block)
    return blocks


def build_blocks_from_parsing_res_list(
    parsing_res_list: list[object],
    page_index: int,
    source_engine: str,
) -> list[Block]:
    """Build blocks from a layout-aware ``parsing_res_list``, keeping its ordering."""
    blocks: list[Block] = []
    for raw_item in parsing_res_list:
        item = normalize_parsing_item(raw_item)
        label = str(item.get("label") or "other")
        content = str(item.get("content") or "").strip()
        poly = to_polygon(item.get("polygon_points"))
        if not poly:
            poly = bbox_to_polygon(item.get("bbox"))
        engine_block_id = item.get("block_id")
        # SDK numeric ids are page-local; use unique ids for response references.
        block_id = engine_block_id if isinstance(engine_block_id, str) and engine_block_id else new_block_id("blk")
        block_order = item.get("block_order")
        blocks.append(
            Block(
                block_id=block_id,
                type=map_label_to_type(label),
                content=content,
                bbox=poly,
                confidence=safe_float(item.get("score"), 0.0),
                page_index=page_index,
                source_engine=source_engine,
                extra={
                    "label": label,
                    "block_order": safe_int(block_order, -1) if block_order is not None else None,
                    "group_id": item.get("group_id"),
                    "engine_block_id": engine_block_id,
                },
            )
        )
    return blocks


def reading_order(blocks: list[Block], *, preserve_input_order: bool = False) -> list[str]:
    """Keep a parsed sequence; only order boxes without an engine sequence."""
    if preserve_input_order:
        return [block.block_id for block in blocks]
    # Missing/invalid/negative block_order sorts to the BACK (large sentinel), not
    # the front: a stored -1 or None must not jump an order-less block ahead of 0.
    def order_of(block: Block) -> int:
        order = safe_int(block.extra.get("block_order"), -1)
        return order if order >= 0 else _NO_ORDER

    has_explicit_order = any(order_of(b) < _NO_ORDER for b in blocks)
    if has_explicit_order:
        return [
            b.block_id
            for b in sorted(
                blocks,
                key=lambda block: (
                    order_of(block),
                    centroid(block.bbox)[1],
                    centroid(block.bbox)[0],
                ),
            )
        ]
    return [b.block_id for b in sorted(blocks, key=lambda block: (centroid(block.bbox)[1], centroid(block.bbox)[0]))]
