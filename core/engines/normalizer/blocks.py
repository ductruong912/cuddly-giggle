"""Build page blocks from the two layout shapes engines produce, and order them."""
from __future__ import annotations

from collections.abc import Iterable

from core.domain.schemas import Block, ConfidenceSource
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
        poly = to_polygon(box.get("coordinate") or box.get("bbox") or box.get("box"))
        raw_score = box.get("score")
        score = safe_float(raw_score, 0.0)
        conf_source = (
            ConfidenceSource.real_engine
            if (raw_score is not None and score > 0.0)
            else ConfidenceSource.unknown
        )
        block = Block(
            block_id=new_block_id("blk"),
            type=map_label_to_type(label),
            content=str(box.get("text", "")).strip(),
            bbox=poly,
            confidence=score,
            confidence_source=conf_source,
            page_index=page_index,
            source_engine=source_engine,
            extra={"label": label},
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
        block_id = str(item.get("block_id") or new_block_id("blk"))
        block_order = item.get("block_order")
        raw_score = item.get("score")
        score = safe_float(raw_score, 0.0)
        conf_source = (
            ConfidenceSource.real_engine
            if (raw_score is not None and score > 0.0)
            else ConfidenceSource.unknown
        )
        blocks.append(
            Block(
                block_id=block_id,
                type=map_label_to_type(label),
                content=content,
                bbox=poly,
                confidence=score,
                confidence_source=conf_source,
                page_index=page_index,
                source_engine=source_engine,
                extra={
                    "label": label,
                    "block_order": safe_int(block_order, -1) if block_order is not None else None,
                    "group_id": item.get("group_id"),
                },
            )
        )
    return blocks


def reading_order(blocks: list[Block]) -> list[str]:
    """Order block ids by the engine's ordering, falling back to top-to-bottom."""
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
