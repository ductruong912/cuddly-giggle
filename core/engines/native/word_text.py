"""Read a .docx/.doc document's text and tables directly from its XML."""
from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any
import xml.etree.ElementTree as ET
import zipfile

from config.config import Settings, settings
from core.domain.schemas import Block, BlockType, ConfidenceSource, PageParseResult, Table, TableCell
from core.engines.base import EngineParseResult, ParseEngine
from core.engines.native.office_shared import clean_text, convert_office, rows_to_markdown


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

WORD_TEXT_CONFIDENCE = 0.99


class WordTextEngine(ParseEngine):
    name = "word_text"

    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings

    def parse(self, input_path: str, lang_hint: str = "auto") -> EngineParseResult:
        """Parse a .docx directly, or convert a legacy .doc first."""
        path = Path(input_path)
        suffix = path.suffix.lower()
        if suffix == ".docx":
            return self._parse_docx(path, raw_extra={"source_suffix": suffix})
        if suffix == ".doc":
            return self._parse_legacy_doc(path)
        return EngineParseResult(engine_name=self.name, pages=[], markdown=None, raw={"reason": "not_word"})

    def _parse_legacy_doc(self, path: Path) -> EngineParseResult:
        with tempfile.TemporaryDirectory(prefix="doc_to_docx_") as temp_dir:
            converted_path = convert_office(path, Path(temp_dir), target_format="docx")
            return self._parse_docx(
                converted_path,
                raw_extra={
                    "source_suffix": ".doc",
                    "converted_from": str(path),
                },
            )

    def _parse_docx(self, path: Path, raw_extra: dict[str, Any] | None = None) -> EngineParseResult:
        try:
            with zipfile.ZipFile(path) as archive:
                document_xml = archive.read("word/document.xml")
        except KeyError as exc:
            raise RuntimeError("Invalid .docx file: missing word/document.xml.") from exc
        except zipfile.BadZipFile as exc:
            raise RuntimeError("Invalid .docx file: not a valid Office Open XML package.") from exc

        try:
            root = ET.fromstring(document_xml)
        except ET.ParseError as exc:
            raise RuntimeError("Invalid .docx file: document.xml could not be parsed.") from exc

        body = root.find(_w("body"))
        if body is None:
            raise RuntimeError("Invalid .docx file: missing document body.")

        blocks: list[Block] = []
        tables: list[Table] = []
        reading_order: list[str] = []
        markdown_parts: list[str] = []
        block_index = 0

        for child in body:
            if child.tag == _w("p"):
                text = _paragraph_text(child)
                if not text:
                    continue
                block_id = f"word_text_p0_b{block_index}"
                blocks.append(
                    Block(
                        block_id=block_id,
                        type=BlockType.text,
                        content=text,
                        confidence=WORD_TEXT_CONFIDENCE,
                        confidence_source=ConfidenceSource.synthesized,
                        page_index=0,
                        source_engine=self.name,
                    )
                )
                reading_order.append(block_id)
                markdown_parts.append(text)
                block_index += 1
                continue

            if child.tag == _w("tbl"):
                rows, table = _extract_table(child, len(tables), WORD_TEXT_CONFIDENCE)
                if table is None:
                    continue
                table_markdown = rows_to_markdown(rows)
                tables.append(table)
                block_id = f"word_text_p0_b{block_index}"
                blocks.append(
                    Block(
                        block_id=block_id,
                        type=BlockType.table,
                        content=table_markdown,
                        confidence=WORD_TEXT_CONFIDENCE,
                        confidence_source=ConfidenceSource.synthesized,
                        page_index=0,
                        source_engine=self.name,
                        extra={"table_id": table.table_id},
                    )
                )
                reading_order.append(block_id)
                if table_markdown:
                    markdown_parts.append(table_markdown)
                block_index += 1

        has_content = bool(blocks or tables)
        page = PageParseResult(
            page_index=0,
            blocks=blocks,
            tables=tables,
            reading_order=reading_order,
            confidence=WORD_TEXT_CONFIDENCE if has_content else 0.0,
            source_engine=self.name,
        )
        raw = {
            "paragraph_count": sum(1 for block in blocks if block.type == BlockType.text),
            "table_count": len(tables),
        }
        if raw_extra:
            raw.update(raw_extra)
        markdown = "\n\n".join(part for part in markdown_parts if part.strip()) or None
        return EngineParseResult(engine_name=self.name, pages=[page], markdown=markdown, raw=raw)


def _extract_table(table_element: ET.Element, table_index: int, confidence: float) -> tuple[list[list[str]], Table | None]:
    rows: list[list[str]] = []
    cells: list[TableCell] = []
    for row_index, row_element in enumerate(table_element.findall(_w("tr"))):
        row_values: list[str] = []
        col_index = 0
        for cell_element in row_element.findall(_w("tc")):
            text = _cell_text(cell_element)
            colspan = _cell_colspan(cell_element)
            row_values.append(text)
            cells.append(
                TableCell(
                    row=row_index,
                    col=col_index,
                    colspan=colspan,
                    text=text,
                    confidence=confidence,
                )
            )
            col_index += colspan
        if any(value.strip() for value in row_values):
            rows.append(row_values)

    if not cells:
        return rows, None

    return rows, Table(
        table_id=f"word_text_tbl_p0_{table_index}",
        page_index=0,
        cells=cells,
        confidence=confidence,
    )


def _cell_text(cell_element: ET.Element) -> str:
    paragraphs = [_paragraph_text(paragraph) for paragraph in cell_element.findall(_w("p"))]
    return "\n".join(paragraph for paragraph in paragraphs if paragraph).strip()


def _paragraph_text(paragraph: ET.Element) -> str:
    parts: list[str] = []
    for element in paragraph.iter():
        if element.tag == _w("t") and element.text:
            parts.append(element.text)
        elif element.tag == _w("tab"):
            parts.append("\t")
        elif element.tag in {_w("br"), _w("cr")}:
            parts.append("\n")
    return clean_text("".join(parts))


def _cell_colspan(cell_element: ET.Element) -> int:
    grid_span = cell_element.find(f"{_w('tcPr')}/{_w('gridSpan')}")
    if grid_span is None:
        return 1
    raw_value = grid_span.attrib.get(_w("val")) or grid_span.attrib.get("val")
    try:
        return max(1, int(raw_value or 1))
    except ValueError:
        return 1


def _w(local_name: str) -> str:
    return f"{{{W_NS}}}{local_name}"
