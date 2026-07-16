from __future__ import annotations

from collections.abc import Iterable
import json
from html import unescape
import re
import uuid

from app.core.config import Settings, settings
from app.domain.schemas import Block, BlockType, PageParseResult, Point, Table, TableCell


def _safe_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: object, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def map_label_to_type(label: str | None) -> BlockType:
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
    if not isinstance(raw_coordinate, list):
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
            points.append(Point(x=_safe_float(item[0]), y=_safe_float(item[1])))
    return points


def _bbox_to_polygon(bbox: object) -> list[Point]:
    if isinstance(bbox, list) and len(bbox) >= 4 and all(isinstance(v, (int, float)) for v in bbox[:4]):
        x1, y1, x2, y2 = bbox[:4]
        return [
            Point(x=float(x1), y=float(y1)),
            Point(x=float(x2), y=float(y1)),
            Point(x=float(x2), y=float(y2)),
            Point(x=float(x1), y=float(y2)),
        ]
    return []


def _centroid(poly: list[Point]) -> tuple[float, float]:
    if not poly:
        return (0.0, 0.0)
    x = sum(p.x for p in poly) / len(poly)
    y = sum(p.y for p in poly) / len(poly)
    return (x, y)


def _new_block_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _avg_positive(values: Iterable[float]) -> float:
    positives = [v for v in values if v > 0.0]
    if not positives:
        return 0.0
    return sum(positives) / len(positives)


def _build_blocks_from_layout_boxes(
    boxes: Iterable[dict],
    page_index: int,
    source_engine: str,
) -> list[Block]:
    blocks: list[Block] = []
    for box in boxes:
        if not isinstance(box, dict):
            continue
        label = str(box.get("label", "")).strip() or "other"
        poly = to_polygon(box.get("coordinate") or box.get("bbox") or box.get("box"))
        block = Block(
            block_id=_new_block_id("blk"),
            type=map_label_to_type(label),
            content=str(box.get("text", "")).strip(),
            bbox=poly,
            confidence=_safe_float(box.get("score"), 0.0),
            page_index=page_index,
            source_engine=source_engine,
            extra={"label": label},
        )
        blocks.append(block)
    return blocks


def _extract_markdown(raw: dict) -> str | None:
    for key in ("markdown", "md", "full_md", "full.markdown", "markdown_texts", "text"):
        if key in raw:
            value = raw[key]
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                nested = _extract_markdown(value)
                if nested:
                    return nested
    return None


def _extract_raw_tables(raw: dict, page_index: int = 0) -> list[Table]:
    tables: list[Table] = []
    candidates = raw.get("tables") or raw.get("table_res_list") or raw.get("table_results") or []
    if not isinstance(candidates, list):
        return tables

    for idx, item in enumerate(candidates):
        if not isinstance(item, dict):
            continue
        cells_raw = item.get("cells")
        cells: list[TableCell] = []
        if isinstance(cells_raw, list) and cells_raw:
            for c in cells_raw:
                if not isinstance(c, dict):
                    continue
                cells.append(
                    TableCell(
                        row=_safe_int(c.get("row"), 0),
                        col=_safe_int(c.get("col"), 0),
                        rowspan=_safe_int(c.get("rowspan"), 1),
                        colspan=_safe_int(c.get("colspan"), 1),
                        text=str(c.get("text", "")),
                        confidence=_safe_float(c.get("score"), 0.0),
                    )
                )
        elif isinstance(item.get("html"), str):
            # PaddleOCR table_res_list often carries only an HTML string (no cell
            # list). Parse real cells from it; fall back to a single flattened cell.
            cells = _parse_table_cells_from_html(item["html"])
            if not cells:
                text = re.sub(r"<[^>]+>", " ", item["html"])
                text = re.sub(r"\s+", " ", text).strip()
                if text:
                    cells = [TableCell(row=0, col=0, text=text, confidence=_safe_float(item.get("score"), 0.0))]

        tables.append(
            Table(
                table_id=str(item.get("table_id") or _new_block_id("tbl")),
                page_index=_safe_int(item.get("page_index"), page_index),
                cells=cells,
                confidence=_safe_float(item.get("score"), 0.0),
            )
        )
    return tables


def _parse_table_cells_from_html(html_text: str) -> list[TableCell]:
    cells: list[TableCell] = []
    # Track grid positions reserved by rowspans started in earlier rows so a cell
    # in a later row is not assigned a column already occupied by a spanning cell.
    occupied: set[tuple[int, int]] = set()
    row_matches = re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, flags=re.IGNORECASE | re.DOTALL)
    for row_idx, row_html in enumerate(row_matches):
        col_idx = 0
        cell_matches = re.findall(r"<(td|th)([^>]*)>(.*?)</(td|th)>", row_html, flags=re.IGNORECASE | re.DOTALL)
        for _, attrs, content, _ in cell_matches:
            text = re.sub(r"<[^>]+>", " ", content)
            text = unescape(re.sub(r"\s+", " ", text).strip())
            rowspan = 1
            colspan = 1
            m_row = re.search(r"rowspan\s*=\s*['\"]?(\d+)", attrs, flags=re.IGNORECASE)
            m_col = re.search(r"colspan\s*=\s*['\"]?(\d+)", attrs, flags=re.IGNORECASE)
            if m_row:
                rowspan = max(_safe_int(m_row.group(1), 1), 1)
            if m_col:
                colspan = max(_safe_int(m_col.group(1), 1), 1)
            # Advance past any column reserved by a rowspan from an earlier row.
            while (row_idx, col_idx) in occupied:
                col_idx += 1
            cells.append(TableCell(row=row_idx, col=col_idx, rowspan=rowspan, colspan=colspan, text=text))
            for dr in range(rowspan):
                for dc in range(colspan):
                    occupied.add((row_idx + dr, col_idx + dc))
            col_idx += colspan
    return cells


def _object_to_dict(item: object) -> dict:
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


def _normalize_parsing_item(item: object) -> dict:
    d = _object_to_dict(item)
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


def _extract_tables_from_parsing_res_list(
    parsing_res_list: list[object],
    page_index: int,
) -> list[Table]:
    tables: list[Table] = []
    for raw_item in parsing_res_list:
        item = _normalize_parsing_item(raw_item)
        label = str(item.get("label") or "").strip().lower()
        if "table" not in label:
            continue
        content = str(item.get("content") or "")
        table_id = str(item.get("block_id") or _new_block_id("tbl"))
        if "<table" in content.lower():
            cells = _parse_table_cells_from_html(content)
        else:
            cells = [TableCell(row=0, col=0, text=content)]
        tables.append(
            Table(
                table_id=table_id,
                page_index=page_index,
                cells=cells,
                confidence=_safe_float(item.get("score"), 0.0),
            )
        )
    return tables


def _extract_tables_from_markdown(markdown_text: str, page_index: int) -> list[Table]:
    table_html_list = re.findall(r"<table\b[^>]*>.*?</table>", markdown_text, flags=re.IGNORECASE | re.DOTALL)
    tables: list[Table] = []
    for html_table in table_html_list:
        cells = _parse_table_cells_from_html(html_table)
        tables.append(
            Table(
                table_id=_new_block_id("tbl"),
                page_index=page_index,
                cells=cells if cells else [TableCell(row=0, col=0, text=html_table)],
                confidence=0.0,
            )
        )
    return tables


def _build_blocks_from_parsing_res_list(
    parsing_res_list: list[object],
    page_index: int,
    source_engine: str,
) -> list[Block]:
    blocks: list[Block] = []
    for raw_item in parsing_res_list:
        item = _normalize_parsing_item(raw_item)
        label = str(item.get("label") or "other")
        content = str(item.get("content") or "").strip()
        poly = to_polygon(item.get("polygon_points"))
        if not poly:
            poly = _bbox_to_polygon(item.get("bbox"))
        block_id = str(item.get("block_id") or _new_block_id("blk"))
        block_order = item.get("block_order")
        blocks.append(
            Block(
                block_id=block_id,
                type=map_label_to_type(label),
                content=content,
                bbox=poly,
                confidence=_safe_float(item.get("score"), 0.0),
                page_index=page_index,
                source_engine=source_engine,
                extra={
                    "label": label,
                    "block_order": _safe_int(block_order, -1) if block_order is not None else None,
                    "group_id": item.get("group_id"),
                },
            )
        )
    return blocks


def _reading_order(blocks: list[Block]) -> list[str]:
    # Missing/invalid/negative block_order sorts to the BACK (large sentinel), not
    # the front: a stored -1 or None must not jump an order-less block ahead of 0.
    def order_of(block: Block) -> int:
        order = _safe_int(block.extra.get("block_order"), -1)
        return order if order >= 0 else 10**9

    has_explicit_order = any(order_of(b) < 10**9 for b in blocks)
    if has_explicit_order:
        return [
            b.block_id
            for b in sorted(
                blocks,
                key=lambda block: (
                    order_of(block),
                    _centroid(block.bbox)[1],
                    _centroid(block.bbox)[0],
                ),
            )
        ]
    return [b.block_id for b in sorted(blocks, key=lambda block: (_centroid(block.bbox)[1], _centroid(block.bbox)[0]))]


def _result_to_dict(raw: object) -> dict:
    if isinstance(raw, dict):
        converted = dict(raw)
        if "res" in converted and not isinstance(converted["res"], (dict, list, str, int, float, bool, type(None))):
            nested = _result_to_dict(converted["res"])
            if nested:
                converted["res"] = nested.get("res", nested)
        if "pages" in converted and isinstance(converted["pages"], list):
            pages: list[object] = converted["pages"]
            converted["pages"] = [
                _result_to_dict(page) if not isinstance(page, dict) else page
                for page in pages
            ]
        if "markdown" in converted and isinstance(converted["markdown"], dict):
            md_text = _extract_markdown(converted["markdown"])
            if md_text:
                converted["markdown"] = md_text
        return converted
    if hasattr(raw, "json"):
        json_attr = getattr(raw, "json")
        try:
            value = json_attr() if callable(json_attr) else json_attr
        except Exception:
            value = None
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
    if hasattr(raw, "__dict__"):
        return dict(vars(raw))
    return {}


def _result_to_markdown_text(raw: object) -> str | None:
    if isinstance(raw, dict):
        md = _extract_markdown(raw)
        if md:
            return md
    if hasattr(raw, "markdown"):
        markdown_attr = getattr(raw, "markdown")
        try:
            value = markdown_attr() if callable(markdown_attr) else markdown_attr
        except Exception:
            value = None
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            md = _extract_markdown(value)
            if md:
                return md
    return None


def _starts_with_text_page_marker(line: str) -> bool:
    return bool(re.match(r"^(?:#{1,6}\s*)?\[Tr\.\s*\d+\s*\]\s*:?", line.strip()))


def _is_standalone_text_page_marker(line: str) -> bool:
    return bool(re.match(r"^(?:#{1,6}\s*)?\[Tr\.\s*\d+\s*\]\s*:?\s*$", line.strip()))


def _text_only_markdown_needs_blank_before(line: str, previous_line: str) -> bool:
    line = line.strip()
    previous_line = previous_line.strip()

    if _starts_with_text_page_marker(line):
        return True
    if _is_standalone_text_page_marker(previous_line):
        return False
    if previous_line.startswith("#"):
        return True
    if re.match(r"^Ngày\b", line, flags=re.IGNORECASE):
        return True
    return line.startswith(("Người dịch:", "Hiệu đính:", "VIỆN ", "VIỆN NGHIÊN"))


def _compact_text_only_markdown(markdown: str | None) -> str | None:
    if markdown is None:
        return None

    text = markdown.strip()
    if not text:
        return None

    # Structured markdown carries meaningful blank lines for tables/code blocks.
    if any(marker in text for marker in ("<table", "```")) or re.search(r"^\s*\|.*\|\s*$", text, re.MULTILINE):
        return text

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None

    compacted = [lines[0]]
    for line in lines[1:]:
        previous_line = compacted[-1]
        if _text_only_markdown_needs_blank_before(line, previous_line):
            compacted.extend(["", line])
        else:
            compacted.append(line)
    return "\n".join(compacted)


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
            md = _result_to_markdown_text(item)
            if md:
                markdown_parts.append(md)
            item_dict = _result_to_dict(item)
            if item_dict:
                raw_items.append(item_dict)
                if "res" in item_dict and isinstance(item_dict["res"], dict):
                    page_dicts.append(item_dict["res"])
                else:
                    page_dicts.append(item_dict)
        normalized_raw = {"pages": page_dicts, "raw_items": raw_items}
    else:
        normalized_raw = _result_to_dict(raw)
        md = _result_to_markdown_text(raw)
        if md:
            markdown_parts.append(md)
        if "res" in normalized_raw and isinstance(normalized_raw["res"], dict):
            md2 = _extract_markdown(normalized_raw["res"])
            if md2:
                markdown_parts.append(md2)

    root = normalized_raw.get("res", normalized_raw)
    # Only reach for a fallback markdown when nothing was already extracted above;
    # otherwise the same top-level markdown gets appended twice and the artifact
    # ends up duplicated (it's the common single-dict / CLI payload shape).
    if not markdown_parts:
        fallback_md = _extract_markdown(normalized_raw) or (_extract_markdown(root) if isinstance(root, dict) else None)
        if fallback_md:
            markdown_parts.append(fallback_md)
    markdown = _compact_text_only_markdown("\n\n".join([part for part in markdown_parts if part.strip()]) or None)

    # import logging
    # _logger = logging.getLogger("app.ocr.pipeline")
    # _logger.info("--- OCR Pipeline Execution Verification ---")
    # _logger.info("Source Engine: %s", source_engine)
    # if markdown:
    #     _logger.info("Raw Markdown output size: %s characters", len(markdown))

    pages: list[PageParseResult] = []
    if isinstance(root, dict) and isinstance(root.get("pages"), list):
        raw_pages = root["pages"]
    elif isinstance(normalized_raw, dict) and isinstance(normalized_raw.get("pages"), list):
        raw_pages = normalized_raw["pages"]
    else:
        raw_pages = [root] if isinstance(root, dict) else []

    for idx, page in enumerate(raw_pages):
        if not isinstance(page, dict):
            continue

        # Prefer the engine's real page index when present; fall back to the
        # positional index. Using the real index keeps page attribution correct
        # even if an earlier page was dropped/compacted.
        page_index = _safe_int(page.get("page_index"), idx)

        parsing_res_list = page.get("parsing_res_list")

        # # Log blocks information to verify detection, size, and downscaling
        # if isinstance(parsing_res_list, list):
        #     _logger.info("Page %s: Detected %s layout blocks in parsing_res_list", page_index, len(parsing_res_list))
        #     for j, block in enumerate(parsing_res_list):
        #         block_dict = _normalize_parsing_item(block)
        #         label = block_dict.get("label")
        #         content = block_dict.get("content") or ""
        #         bbox = block_dict.get("bbox") or []
                
        #         width, height = 0.0, 0.0
        #         if isinstance(bbox, list):
        #             if len(bbox) == 4 and all(isinstance(v, (int, float)) for v in bbox):
        #                 width = abs(bbox[2] - bbox[0])
        #                 height = abs(bbox[3] - bbox[1])
        #             elif len(bbox) >= 2:
        #                 try:
        #                     xs = [float(p[0] if isinstance(p, (list, tuple)) else p.x) for p in bbox]
        #                     ys = [float(p[1] if isinstance(p, (list, tuple)) else p.y) for p in bbox]
        #                     width = max(xs) - min(xs)
        #                     height = max(ys) - min(ys)
        #                 except Exception:
        #                     pass
                
        #         max_pixels = app_settings.paddleocr_vl_max_pixels if hasattr(app_settings, "paddleocr_vl_max_pixels") else 1003520
        #         total_pixels = width * height
        #         _logger.info(
        #             "  [Layout Block %s] label='%s' | original_size=%sx%s | total_pixels=%s | max_pixels=%s",
        #             j, label, int(width), int(height), int(total_pixels), max_pixels
        #         )
        #         if total_pixels > max_pixels:
        #             scale = (max_pixels / total_pixels) ** 0.5
        #             target_w = int(width * scale)
        #             target_h = int(height * scale)
        #             _logger.info("    => DOWNSCALED BEFORE VLM INFERENCE: %sx%s to %sx%s", int(width), int(height), target_w, target_h)
        #         else:
        #             _logger.info("    => SENT AT NATIVE RESOLUTION TO VLM")
                
        #         _logger.info("    => Recognized text: '%s'", content.strip().replace("\n", " "))

        parsed_blocks: list[Block] = []
        parsed_tables: list[Table] = []
        if isinstance(parsing_res_list, list):
            parsed_blocks = _build_blocks_from_parsing_res_list(parsing_res_list, page_index, source_engine)
            parsed_tables = _extract_tables_from_parsing_res_list(parsing_res_list, page_index)

        boxes: list[dict] = []
        layout = page.get("layout_det_res")
        if isinstance(layout, dict) and isinstance(layout.get("boxes"), list):
            boxes.extend(layout["boxes"])
        if isinstance(page.get("boxes"), list):
            boxes.extend([b for b in page["boxes"] if isinstance(b, dict)])
        if isinstance(page.get("blocks"), list):
            boxes.extend([b for b in page["blocks"] if isinstance(b, dict)])

        blocks = parsed_blocks or _build_blocks_from_layout_boxes(boxes, page_index, source_engine)
        tables = parsed_tables or _extract_raw_tables(page, page_index)

        # Tables exposed only as HTML inside this page's own markdown: parse them
        # here so they are attributed to THIS page, not dumped onto page 0.
        if not tables:
            page_md = _extract_markdown(page)
            if page_md:
                tables = _extract_tables_from_markdown(page_md, page_index=page_index)

        # No explicit blocks from the engine: create one text block fallback.
        if not blocks and isinstance(page.get("text"), str):
            blocks = [
                Block(
                    block_id=_new_block_id("blk"),
                    type=BlockType.text,
                    content=page["text"],
                    bbox=[],
                    confidence=_safe_float(page.get("score"), 0.0),
                    page_index=page_index,
                    source_engine=source_engine,
                )
            ]

        confidence = _safe_float(page.get("score"), 0.0)
        if confidence == 0.0 and boxes:
            confidence = _avg_positive(_safe_float(box.get("score"), 0.0) for box in boxes if isinstance(box, dict))
        if confidence == 0.0 and blocks:
            confidence = _avg_positive(block.confidence for block in blocks)
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

        pages.append(
            PageParseResult(
                page_index=page_index,
                blocks=blocks,
                tables=tables,
                reading_order=_reading_order(blocks),
                confidence=confidence,
                source_engine=source_engine,
            )
        )

    if markdown and len(pages) == 1 and not pages[0].tables:
        md_tables = _extract_tables_from_markdown(markdown, page_index=pages[0].page_index)
        if md_tables:
            pages[0] = pages[0].model_copy(update={"tables": md_tables})

    return pages, markdown, normalized_raw
