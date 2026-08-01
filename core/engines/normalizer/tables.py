"""Recover table cells from the several forms engines emit them in.

PaddleOCR may hand back an explicit cell list, an HTML string, or nothing but a
table embedded in the page Markdown; all three end up as the same ``Table``.
"""
from __future__ import annotations

from html import unescape
import re

from core.domain.schemas import Table, TableCell
from core.engines.normalizer.coercion import (
    new_block_id,
    normalize_parsing_item,
    safe_float,
    safe_int,
)


_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", flags=re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"<(td|th)([^>]*)>(.*?)</(td|th)>", flags=re.IGNORECASE | re.DOTALL)
_TABLE_RE = re.compile(r"<table\b[^>]*>.*?</table>", flags=re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_ROWSPAN_RE = re.compile(r"rowspan\s*=\s*['\"]?(\d+)", flags=re.IGNORECASE)
_COLSPAN_RE = re.compile(r"colspan\s*=\s*['\"]?(\d+)", flags=re.IGNORECASE)


def parse_table_cells_from_html(html_text: str) -> list[TableCell]:
    """Parse an HTML table into positioned cells, honouring row and column spans."""
    cells: list[TableCell] = []
    # Track grid positions reserved by rowspans started in earlier rows so a cell
    # in a later row is not assigned a column already occupied by a spanning cell.
    occupied: set[tuple[int, int]] = set()
    for row_idx, row_html in enumerate(_ROW_RE.findall(html_text)):
        col_idx = 0
        for _, attrs, content, _ in _CELL_RE.findall(row_html):
            text = _TAG_RE.sub(" ", content)
            text = unescape(re.sub(r"\s+", " ", text).strip())
            rowspan = 1
            colspan = 1
            m_row = _ROWSPAN_RE.search(attrs)
            m_col = _COLSPAN_RE.search(attrs)
            if m_row:
                rowspan = max(safe_int(m_row.group(1), 1), 1)
            if m_col:
                colspan = max(safe_int(m_col.group(1), 1), 1)
            # Advance past any column reserved by a rowspan from an earlier row.
            while (row_idx, col_idx) in occupied:
                col_idx += 1
            cells.append(TableCell(row=row_idx, col=col_idx, rowspan=rowspan, colspan=colspan, text=text))
            for dr in range(rowspan):
                for dc in range(colspan):
                    occupied.add((row_idx + dr, col_idx + dc))
            col_idx += colspan
    return cells


def extract_raw_tables(raw: dict, page_index: int = 0) -> list[Table]:
    """Build tables from a page's ``tables`` / ``table_res_list`` / ``table_results``."""
    tables: list[Table] = []
    candidates = raw.get("tables") or raw.get("table_res_list") or raw.get("table_results") or []
    if not isinstance(candidates, list):
        return tables

    for item in candidates:
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
                        row=safe_int(c.get("row"), 0),
                        col=safe_int(c.get("col"), 0),
                        rowspan=safe_int(c.get("rowspan"), 1),
                        colspan=safe_int(c.get("colspan"), 1),
                        text=str(c.get("text", "")),
                        confidence=safe_float(c.get("score"), 0.0),
                    )
                )
        elif isinstance(item.get("html"), str):
            # PaddleOCR table_res_list often carries only an HTML string (no cell
            # list). Parse real cells from it; fall back to a single flattened cell.
            cells = parse_table_cells_from_html(item["html"])
            if not cells:
                text = _TAG_RE.sub(" ", item["html"])
                text = re.sub(r"\s+", " ", text).strip()
                if text:
                    cells = [TableCell(row=0, col=0, text=text, confidence=safe_float(item.get("score"), 0.0))]

        tables.append(
            Table(
                table_id=str(item.get("table_id") or new_block_id("tbl")),
                page_index=safe_int(item.get("page_index"), page_index),
                cells=cells,
                confidence=safe_float(item.get("score"), 0.0),
            )
        )
    return tables


def extract_tables_from_parsing_res_list(
    parsing_res_list: list[object],
    page_index: int,
) -> list[Table]:
    """Build tables from the table-labelled entries of a ``parsing_res_list``."""
    tables: list[Table] = []
    for raw_item in parsing_res_list:
        item = normalize_parsing_item(raw_item)
        label = str(item.get("label") or "").strip().lower()
        if "table" not in label:
            continue
        content = str(item.get("content") or "")
        table_id = str(item.get("block_id") or new_block_id("tbl"))
        if "<table" in content.lower():
            cells = parse_table_cells_from_html(content)
        else:
            cells = [TableCell(row=0, col=0, text=content)]
        tables.append(
            Table(
                table_id=table_id,
                page_index=page_index,
                cells=cells,
                confidence=safe_float(item.get("score"), 0.0),
            )
        )
    return tables


def extract_tables_from_markdown(markdown_text: str, page_index: int) -> list[Table]:
    """Build tables from any HTML tables embedded in a page's Markdown."""
    tables: list[Table] = []
    for html_table in _TABLE_RE.findall(markdown_text):
        cells = parse_table_cells_from_html(html_table)
        tables.append(
            Table(
                table_id=new_block_id("tbl"),
                page_index=page_index,
                cells=cells if cells else [TableCell(row=0, col=0, text=html_table)],
                confidence=0.0,
            )
        )
    return tables
