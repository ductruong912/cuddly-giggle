"""Assemble adapter-specific engine output into the stable internal page schema."""
from __future__ import annotations

from config.config import Settings, settings
from core.domain.schemas import (
    Block,
    BlockType,
    ConfidenceSource,
    CoordinateSpace,
    PageGeometry,
    PageParseResult,
    Table,
)
from core.engines.normalizer.blocks import (
    build_blocks_from_layout_boxes,
    build_blocks_from_parsing_res_list,
    reading_order,
)
from core.engines.normalizer.coercion import (
    avg_positive,
    new_block_id,
    result_to_dict,
    safe_float,
    safe_int,
)
from core.engines.normalizer.markdown_text import (
    compact_text_only_markdown,
    extract_markdown,
    result_to_markdown_text,
)
from core.engines.normalizer.tables import (
    extract_raw_tables,
    extract_tables_from_markdown,
    extract_tables_from_parsing_res_list,
)


def normalize_engine_output(
    raw: object,
    source_engine: str,
    app_settings: Settings = settings,
) -> tuple[list[PageParseResult], str | None, dict]:
    """
    Convert adapter-specific output into a stable internal page schema.
    """
    markdown_parts: list[str] = []
    normalized_raw: dict = {}

    # raw can be single result object, dict, or list of result objects.
    if isinstance(raw, list):
        page_dicts: list[dict] = []
        raw_items: list[dict] = []
        for item in raw:
            md = result_to_markdown_text(item)
            if md:
                markdown_parts.append(md)
            item_dict = result_to_dict(item)
            if item_dict:
                raw_items.append(item_dict)
                if "res" in item_dict and isinstance(item_dict["res"], dict):
                    page_dicts.append(item_dict["res"])
                else:
                    page_dicts.append(item_dict)
        normalized_raw = {"pages": page_dicts, "raw_items": raw_items}
    else:
        normalized_raw = result_to_dict(raw)
        md = result_to_markdown_text(raw)
        if md:
            markdown_parts.append(md)
        if "res" in normalized_raw and isinstance(normalized_raw["res"], dict):
            md2 = extract_markdown(normalized_raw["res"])
            if md2:
                markdown_parts.append(md2)

    root = normalized_raw.get("res", normalized_raw)
    # Only reach for a fallback markdown when nothing was already extracted above;
    # otherwise the same top-level markdown gets appended twice and the artifact
    # ends up duplicated (it's the common single-dict / CLI payload shape).
    if not markdown_parts:
        fallback_md = extract_markdown(normalized_raw) or (extract_markdown(root) if isinstance(root, dict) else None)
        if fallback_md:
            markdown_parts.append(fallback_md)
    markdown = compact_text_only_markdown("\n\n".join([part for part in markdown_parts if part.strip()]) or None)

    pages = _build_pages(normalized_raw, root, source_engine, app_settings)

    if markdown and len(pages) == 1 and not pages[0].tables:
        md_tables = extract_tables_from_markdown(markdown, page_index=pages[0].page_index)
        if md_tables:
            pages[0] = pages[0].model_copy(update={"tables": md_tables})

    return pages, markdown, normalized_raw


def _build_pages(
    normalized_raw: dict,
    root: object,
    source_engine: str,
    app_settings: Settings,
) -> list[PageParseResult]:
    pages: list[PageParseResult] = []
    for idx, page in enumerate(_raw_pages(normalized_raw, root)):
        if not isinstance(page, dict):
            continue

        # Prefer the engine's real page index when present; fall back to the
        # positional index. Using the real index keeps page attribution correct
        # even if an earlier page was dropped/compacted.
        page_index = safe_int(page.get("page_index"), idx)

        parsing_res_list = page.get("parsing_res_list")
        parsed_blocks: list[Block] = []
        parsed_tables: list[Table] = []
        if isinstance(parsing_res_list, list):
            parsed_blocks = build_blocks_from_parsing_res_list(parsing_res_list, page_index, source_engine)
            parsed_tables = extract_tables_from_parsing_res_list(parsing_res_list, page_index)

        boxes = _layout_boxes(page)
        blocks = parsed_blocks or build_blocks_from_layout_boxes(boxes, page_index, source_engine)
        tables = parsed_tables or extract_raw_tables(page, page_index)

        # Tables exposed only as HTML inside this page's own markdown: parse them
        # here so they are attributed to THIS page, not dumped onto page 0.
        if not tables:
            page_md = extract_markdown(page)
            if page_md:
                tables = extract_tables_from_markdown(page_md, page_index=page_index)

        # No explicit blocks from the engine: create one text block fallback.
        if not blocks and isinstance(page.get("text"), str):
            raw_sc = page.get("score")
            sc = safe_float(raw_sc, 0.0)
            conf_src = ConfidenceSource.synthesized if (raw_sc is not None and sc > 0.0) else ConfidenceSource.unknown
            blocks = [
                Block(
                    block_id=new_block_id("blk"),
                    type=BlockType.text,
                    content=page["text"],
                    bbox=[],
                    confidence=sc,
                    confidence_source=conf_src,
                    page_index=page_index,
                    source_engine=source_engine,
                )
            ]

        # Extract page dimensions if available
        width = safe_float(page.get("width"), 0.0)
        height = safe_float(page.get("height"), 0.0)
        if width == 0.0 or height == 0.0:
            doc_prep = page.get("doc_preprocessor_res")
            if isinstance(doc_prep, dict):
                out_img = doc_prep.get("output_img") or doc_prep.get("input_img")
                if hasattr(out_img, "shape") and len(out_img.shape) >= 2:
                    height = float(out_img.shape[0])
                    width = float(out_img.shape[1])
            elif hasattr(page.get("input_img"), "shape"):
                img = page["input_img"]
                height = float(img.shape[0])
                width = float(img.shape[1])

        coord_space = CoordinateSpace.none
        if width > 0 and height > 0:
            coord_space = (
                CoordinateSpace.pdf_points
                if source_engine == "pdf_text"
                else CoordinateSpace.processed_image_pixels
            )

        geometry = PageGeometry(width=width, height=height, coordinate_space=coord_space)

        pages.append(
            PageParseResult(
                page_index=page_index,
                geometry=geometry,
                blocks=blocks,
                tables=tables,
                reading_order=reading_order(blocks),
                confidence=_page_confidence(page, boxes, blocks, tables, app_settings),
                source_engine=source_engine,
            )
        )
    return pages


def _raw_pages(normalized_raw: dict, root: object) -> list[object]:
    if isinstance(root, dict) and isinstance(root.get("pages"), list):
        return root["pages"]
    if isinstance(normalized_raw, dict) and isinstance(normalized_raw.get("pages"), list):
        return normalized_raw["pages"]
    return [root] if isinstance(root, dict) else []


def _layout_boxes(page: dict) -> list[dict]:
    boxes: list[dict] = []
    layout = page.get("layout_det_res")
    if isinstance(layout, dict) and isinstance(layout.get("boxes"), list):
        boxes.extend(layout["boxes"])
    if isinstance(page.get("boxes"), list):
        boxes.extend([b for b in page["boxes"] if isinstance(b, dict)])
    if isinstance(page.get("blocks"), list):
        boxes.extend([b for b in page["blocks"] if isinstance(b, dict)])
    return boxes


def _page_confidence(
    page: dict,
    boxes: list[dict],
    blocks: list[Block],
    tables: list[Table],
    app_settings: Settings,
) -> float:
    confidence = safe_float(page.get("score"), 0.0)
    if confidence == 0.0 and boxes:
        confidence = avg_positive(safe_float(box.get("score"), 0.0) for box in boxes if isinstance(box, dict))
    if confidence == 0.0 and blocks:
        confidence = avg_positive(block.confidence for block in blocks)
    if confidence == 0.0 and blocks:
        non_empty = sum(1 for block in blocks if (block.content or "").strip())
        # Only synthesize a confidence floor when the page actually recognized
        # text. A page with blocks but zero text stays at 0.0 (low) instead of
        # being inflated to the base floor.
        if non_empty:
            content_ratio = non_empty / len(blocks)
            confidence = min(
                app_settings.normalizer_confidence_cap,
                app_settings.normalizer_confidence_base
                + app_settings.normalizer_confidence_content_weight * content_ratio
                + (app_settings.normalizer_confidence_table_bonus if tables else 0.0),
            )
    return confidence
