"""Native document text extraction engines (PDF / Word / Excel).

Each engine reads a document's existing text layer without OCR. The three
engines share the LibreOffice conversion path (legacy .doc/.xls) and the
markdown-table helpers at the bottom of this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
import shutil
from statistics import median
import subprocess
import tempfile
from typing import Any
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

from config.config import Settings, settings
from core.domain.schemas import Block, BlockType, PageParseResult, Point, Table, TableCell
from core.engines.base import EngineParseResult, ParseEngine


CONVERSION_TIMEOUT_SECONDS = 60

# Native fast-path tuning (fixed constants; previously env-configurable).
PDF_TEXT_MIN_TOTAL_CHARS = 80
PDF_TEXT_MIN_CHARS_PER_TEXT_PAGE = 40
PDF_TEXT_MIN_TEXT_PAGES_RATIO = 1.0

PDF_TEXT_MIN_READABLE_RATIO = 0.70

PDF_TEXT_MAX_CORRUPT_WORD_RATIO = 0.07

PDF_TEXT_MIN_WORDS_FOR_CORRUPT_CHECK = 20
PDF_TEXT_CONFIDENCE = 0.98
WORD_TEXT_CONFIDENCE = 0.99
EXCEL_TEXT_CONFIDENCE = 0.99


# =====================================================================================
# PDF
# =====================================================================================

_TCVN3_CHARS = "ÂµÂ¸Â¶Â·Â¹Â¨Â»Â¾Â¼Â½Ã†Â©Ã‡ÃŠÃˆÃ‰Ã‹Â®ÃŒÃÃŽÃÃ‘ÂªÃ’Ã•Ã“Ã”Ã–Ã—ÃÃ˜ÃœÃžÃŸÃ£Ã¡Ã¢Ã¤Â«Ã¥Ã¨Ã¦Ã§Ã©Â¬ÃªÃ­Ã«Ã¬Ã®Ã¯Ã³Ã±Ã²Ã´Â­ÃµÃ¸Ã¶Ã·Ã¹ÃºÃ½Ã»Ã¼Ã¾Â¡Â¢Â§Â£Â¤Â¥Â¦"
_UNICODE_CHARS = "Ã Ã¡áº£Ã£áº¡Äƒáº±áº¯áº³áºµáº·Ã¢áº§áº¥áº©áº«áº­Ä‘Ã¨Ã©áº»áº½áº¹Ãªá»áº¿á»ƒá»…á»‡Ã¬Ã­á»‰Ä©á»‹Ã²Ã³á»Ãµá»Ã´á»“á»‘á»•á»—á»™Æ¡á»á»›á»Ÿá»¡á»£Ã¹Ãºá»§Å©á»¥Æ°á»«á»©á»­á»¯á»±á»³Ã½á»·á»¹á»µÄ‚Ã‚ÄÃŠÃ”Æ Æ¯"
_TCVN3_TRANSLATION = str.maketrans(dict(zip(_TCVN3_CHARS, _UNICODE_CHARS)))
_TCVN3_MARKERS = frozenset(_TCVN3_CHARS)


@dataclass(frozen=True)
class PdfWord:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return max(1.0, self.y1 - self.y0)


@dataclass(frozen=True)
class TextSegment:
    x0: float
    x1: float
    text: str


class PdfTextEngine(ParseEngine):
    name = "pdf_text"

    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings

    def parse(self, input_path: str, lang_hint: str = "auto") -> EngineParseResult:
        if Path(input_path).suffix.lower() != ".pdf":
            return EngineParseResult(engine_name=self.name, pages=[], markdown=None, raw={"reason": "not_pdf"})

        try:
            import fitz  # type: ignore
        except Exception as exc:
            raise RuntimeError("PyMuPDF is unavailable. Install PyMuPDF to parse text PDFs.") from exc

        doc = fitz.open(input_path)
        try:
            pages: list[PageParseResult] = []
            markdown_parts: list[str] = []
            raw_pages: list[dict[str, Any]] = []
            for page_index, page in enumerate(doc):
                text_dict = page.get_text("dict") or {}
                raw_blocks = text_dict.get("blocks", [])
                raw_words = _get_page_words(page)
                blocks = self._extract_page_blocks(raw_blocks, page_index)
                tables = _extract_tables_from_words(raw_words, page_index, PDF_TEXT_CONFIDENCE)
                page_markdown = _build_layout_markdown(raw_words)
                if blocks:
                    markdown_parts.append(
                        page_markdown or "\n".join(block.content for block in blocks if block.content.strip())
                    )
                pages.append(
                    PageParseResult(
                        page_index=page_index,
                        blocks=blocks,
                        tables=tables,
                        reading_order=[block.block_id for block in blocks],
                        confidence=PDF_TEXT_CONFIDENCE if blocks else 0.0,
                        source_engine=self.name,
                    )
                )
                raw_pages.append({"page_index": page_index, "blocks": raw_blocks, "words": raw_words})
        finally:
            doc.close()

        markdown = "\n\n".join(part for part in markdown_parts if part.strip()) or None
        return EngineParseResult(
            engine_name=self.name,
            pages=pages,
            markdown=markdown,
            raw={"pages": raw_pages},
        )

    def _extract_page_blocks(self, raw_blocks: object, page_index: int) -> list[Block]:
        if not isinstance(raw_blocks, list):
            return []

        blocks: list[Block] = []
        for block_index, raw_block in enumerate(raw_blocks):
            if not isinstance(raw_block, dict):
                continue
            if raw_block.get("type", 0) != 0:
                continue
            content = repair_legacy_vietnamese_text(_extract_block_text(raw_block))
            if not content:
                continue
            blocks.append(
                Block(
                    block_id=f"pdf_text_p{page_index}_b{block_index}",
                    type=BlockType.text,
                    content=content,
                    bbox=_bbox_to_polygon(raw_block.get("bbox")),
                    confidence=PDF_TEXT_CONFIDENCE,
                    page_index=page_index,
                    source_engine=self.name,
                    extra={"block_order": block_index},
                )
            )
        return blocks


def repair_legacy_vietnamese_text(text: str) -> str:
    """Convert common TCVN3/ABC printer-PDF text into Unicode Vietnamese."""
    if not text:
        return text
    if not any(ch in _TCVN3_MARKERS for ch in text):
        return text
    return text.translate(_TCVN3_TRANSLATION)


def _get_page_words(page: object) -> list[object]:
    try:
        words = page.get_text("words")  # type: ignore[attr-defined]
    except Exception:
        return []
    return words if isinstance(words, list) else []


def _build_layout_markdown(raw_words: list[object]) -> str | None:
    lines = _group_words_into_lines(raw_words)
    if not lines:
        return None

    min_x = min(word.x0 for line in lines for word in line)
    rendered = [_format_layout_line(_segments_for_line(line), min_x) for line in lines]
    rendered = [line.rstrip() for line in rendered if line.strip()]
    if not rendered:
        return None
    return "```text\n" + "\n".join(rendered) + "\n```"


def _extract_tables_from_words(raw_words: list[object], page_index: int, confidence: float) -> list[Table]:
    rows: list[list[TextSegment]] = []
    for line in _group_words_into_lines(raw_words):
        segments = _segments_for_line(line)
        if len(segments) >= 3:
            rows.append(segments)

    if len(rows) < 2:
        return []

    cells: list[TableCell] = []
    for row_idx, row in enumerate(rows):
        for col_idx, segment in enumerate(row):
            cells.append(TableCell(row=row_idx, col=col_idx, text=segment.text, confidence=confidence))

    return [
        Table(
            table_id=f"pdf_text_tbl_p{page_index}_0",
            page_index=page_index,
            cells=cells,
            confidence=confidence,
        )
    ]


def _group_words_into_lines(raw_words: list[object]) -> list[list[PdfWord]]:
    words = _normalize_words(raw_words)
    if not words:
        return []

    y_tolerance = max(2.0, median(word.height for word in words) * 0.65)
    lines: list[list[PdfWord]] = []
    for word in sorted(words, key=lambda item: (item.center_y, item.x0)):
        if lines and abs(word.center_y - _line_center_y(lines[-1])) <= y_tolerance:
            lines[-1].append(word)
        else:
            lines.append([word])

    return [sorted(line, key=lambda item: item.x0) for line in lines]


def _segments_for_line(words: list[PdfWord]) -> list[TextSegment]:
    if not words:
        return []

    gap_threshold = max(12.0, median(word.height for word in words) * 1.25)
    segments: list[TextSegment] = []
    current_words = [words[0]]
    for word in words[1:]:
        gap = word.x0 - current_words[-1].x1
        if gap > gap_threshold:
            segments.append(_words_to_segment(current_words))
            current_words = [word]
        else:
            current_words.append(word)
    segments.append(_words_to_segment(current_words))
    return segments


def _format_layout_line(segments: list[TextSegment], min_x: float) -> str:
    line = ""
    for segment in segments:
        target_col = max(0, int(round((segment.x0 - min_x) / 6.0)))
        if line:
            line += " " * max(1, target_col - len(line))
        elif target_col:
            line += " " * target_col
        line += segment.text
    return line


def _normalize_words(raw_words: list[object]) -> list[PdfWord]:
    normalized: list[PdfWord] = []
    for raw_word in raw_words:
        if isinstance(raw_word, (list, tuple)) and len(raw_word) >= 5:
            try:
                x0, y0, x1, y1 = (float(raw_word[0]), float(raw_word[1]), float(raw_word[2]), float(raw_word[3]))
            except (TypeError, ValueError):
                continue
            text = repair_legacy_vietnamese_text(str(raw_word[4])).strip()
            if text:
                normalized.append(PdfWord(x0=x0, y0=y0, x1=x1, y1=y1, text=text))
    return normalized


def _line_center_y(words: list[PdfWord]) -> float:
    return sum(word.center_y for word in words) / len(words)


def _words_to_segment(words: list[PdfWord]) -> TextSegment:
    return TextSegment(
        x0=min(word.x0 for word in words),
        x1=max(word.x1 for word in words),
        text=" ".join(word.text for word in words),
    )


def is_pdf_text_result_usable(result: EngineParseResult) -> bool:
    if not result.pages:
        return False

    page_texts = ["\n".join(block.content for block in page.blocks) for page in result.pages]
    page_char_counts = [_useful_char_count(text) for text in page_texts]
    total_chars = sum(page_char_counts)
    if total_chars < PDF_TEXT_MIN_TOTAL_CHARS:
        return False

    text_pages = sum(1 for count in page_char_counts if count >= PDF_TEXT_MIN_CHARS_PER_TEXT_PAGE)
    if text_pages / len(result.pages) < PDF_TEXT_MIN_TEXT_PAGES_RATIO:
        return False

    combined_text = "".join(page_texts)
    # Reject a present-but-garbled text layer (undecodable glyphs) so it falls to OCR.
    if _readable_char_ratio(combined_text) < PDF_TEXT_MIN_READABLE_RATIO:
        return False

    # Reject a text layer that decoded to valid-but-wrong letters (broken font cmap).
    corrupt_ratio, word_count = _corrupt_word_ratio(combined_text)
    if word_count >= PDF_TEXT_MIN_WORDS_FOR_CORRUPT_CHECK and corrupt_ratio > PDF_TEXT_MAX_CORRUPT_WORD_RATIO:
        return False

    return True


def _corrupt_word_ratio(text: str) -> tuple[float, int]:
    """Share of letter-dominant tokens with a digit wedged inside (e.g. "Nguy6n")."""
    considered = 0
    corrupted = 0
    for token in text.split():
        letters = sum(1 for ch in token if ch.isalpha())
        if letters < 2:
            continue
        considered += 1
        digits = sum(1 for ch in token if ch.isdigit())
        if 1 <= digits < letters:
            corrupted += 1
    if considered == 0:
        return 0.0, 0
    return corrupted / considered, considered


def _readable_char_ratio(text: str) -> float:
    """Fraction of non-space characters that decode to meaningful Unicode."""
    chars = [ch for ch in text if not ch.isspace()]
    if not chars:
        return 0.0
    readable = sum(1 for ch in chars if _is_readable_char(ch))
    return readable / len(chars)


def _is_readable_char(ch: str) -> bool:
    code = ord(ch)
    # Private-use areas and the replacement char are what PyMuPDF emits for glyphs
    # it cannot map to real Unicode (broken/missing ToUnicode CMap).
    if ch == "ï¿½":
        return False
    if 0xE000 <= code <= 0xF8FF or 0xF0000 <= code <= 0xFFFFD or 0x100000 <= code <= 0x10FFFD:
        return False
    # Letters, marks (Vietnamese combining diacritics), numbers, punctuation, symbols.
    # Excludes control/format/surrogate/unassigned/private categories.
    return unicodedata.category(ch)[0] in {"L", "M", "N", "P", "S"}


def _extract_block_text(raw_block: dict[str, Any]) -> str:
    lines = raw_block.get("lines")
    if not isinstance(lines, list):
        return ""

    text_lines: list[str] = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        spans = line.get("spans")
        if not isinstance(spans, list):
            continue
        line_text = "".join(str(span.get("text", "")) for span in spans if isinstance(span, dict)).strip()
        if line_text:
            text_lines.append(line_text)
    return "\n".join(text_lines).strip()


def _bbox_to_polygon(raw_bbox: object) -> list[Point]:
    if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) < 4:
        return []
    try:
        x1, y1, x2, y2 = (float(raw_bbox[0]), float(raw_bbox[1]), float(raw_bbox[2]), float(raw_bbox[3]))
    except (TypeError, ValueError):
        return []
    return [
        Point(x=x1, y=y1),
        Point(x=x2, y=y1),
        Point(x=x2, y=y2),
        Point(x=x1, y=y2),
    ]


def _useful_char_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


# =====================================================================================
# Word (.doc / .docx)
# =====================================================================================

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


class WordTextEngine(ParseEngine):
    name = "word_text"

    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings

    def parse(self, input_path: str, lang_hint: str = "auto") -> EngineParseResult:
        path = Path(input_path)
        suffix = path.suffix.lower()
        if suffix == ".docx":
            return self._parse_docx(path, raw_extra={"source_suffix": suffix})
        if suffix == ".doc":
            return self._parse_legacy_doc(path)
        return EngineParseResult(engine_name=self.name, pages=[], markdown=None, raw={"reason": "not_word"})

    def _parse_legacy_doc(self, path: Path) -> EngineParseResult:
        with tempfile.TemporaryDirectory(prefix="doc_to_docx_") as temp_dir:
            converted_path = _convert_office(path, Path(temp_dir), target_format="docx")
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
                table_markdown = _rows_to_markdown(rows)
                tables.append(table)
                block_id = f"word_text_p0_b{block_index}"
                blocks.append(
                    Block(
                        block_id=block_id,
                        type=BlockType.table,
                        content=table_markdown,
                        confidence=WORD_TEXT_CONFIDENCE,
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
    return _clean_text("".join(parts))


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


# =====================================================================================
# Excel (.xls / .xlsx / .xlsm)
# =====================================================================================

SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


@dataclass(frozen=True)
class SheetRef:
    name: str
    path: str


class ExcelTextEngine(ParseEngine):
    name = "excel_text"

    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings

    def parse(self, input_path: str, lang_hint: str = "auto") -> EngineParseResult:
        path = Path(input_path)
        suffix = path.suffix.lower()
        if suffix in {".xlsx", ".xlsm"}:
            return self._parse_xlsx(path, raw_extra={"source_suffix": suffix})
        if suffix == ".xls":
            return self._parse_legacy_xls(path)
        return EngineParseResult(engine_name=self.name, pages=[], markdown=None, raw={"reason": "not_excel"})

    def _parse_legacy_xls(self, path: Path) -> EngineParseResult:
        with tempfile.TemporaryDirectory(prefix="xls_to_xlsx_") as temp_dir:
            converted_path = _convert_office(path, Path(temp_dir), target_format="xlsx")
            return self._parse_xlsx(
                converted_path,
                raw_extra={
                    "source_suffix": ".xls",
                    "converted_from": str(path),
                },
            )

    def _parse_xlsx(self, path: Path, raw_extra: dict[str, Any] | None = None) -> EngineParseResult:
        try:
            with zipfile.ZipFile(path) as archive:
                workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
                rels_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
                shared_strings = _load_shared_strings(archive)
                sheet_refs = _extract_sheet_refs(workbook_root, rels_root)
                pages = [_parse_sheet(archive, sheet_ref, index, shared_strings, EXCEL_TEXT_CONFIDENCE)
                        for index, sheet_ref in enumerate(sheet_refs)]
        except KeyError as exc:
            raise RuntimeError(f"Invalid Excel file: missing {exc.args[0]}.") from exc
        except zipfile.BadZipFile as exc:
            raise RuntimeError("Invalid Excel file: not a valid Office Open XML package.") from exc
        except ET.ParseError as exc:
            raise RuntimeError("Invalid Excel file: workbook XML could not be parsed.") from exc

        pages = [page for page in pages if page.blocks or page.tables]
        markdown_parts = []
        for page in pages:
            for block in page.blocks:
                if block.content.strip():
                    markdown_parts.append(block.content)

        raw = {
            "sheet_count": len(sheet_refs),
            "parsed_sheet_count": len(pages),
        }
        if raw_extra:
            raw.update(raw_extra)

        return EngineParseResult(
            engine_name=self.name,
            pages=pages,
            markdown="\n\n".join(markdown_parts) or None,
            raw=raw,
        )


def _parse_sheet(
    archive: zipfile.ZipFile,
    sheet_ref: SheetRef,
    page_index: int,
    shared_strings: list[str],
    confidence: float,
) -> PageParseResult:
    try:
        sheet_root = ET.fromstring(archive.read(sheet_ref.path))
    except ET.ParseError as exc:
        raise RuntimeError(f"Invalid Excel file: worksheet {sheet_ref.name} could not be parsed.") from exc

    rows = _extract_rows(sheet_root, shared_strings)
    table_markdown = _sheet_to_markdown(sheet_ref.name, rows)
    blocks: list[Block] = []
    tables: list[Table] = []
    reading_order: list[str] = []

    if table_markdown:
        block_id = f"excel_text_p{page_index}_b0"
        table = _rows_to_table(rows, page_index, confidence)
        if table is not None:
            tables.append(table)
        blocks.append(
            Block(
                block_id=block_id,
                type=BlockType.table,
                content=table_markdown,
                confidence=confidence,
                page_index=page_index,
                source_engine=ExcelTextEngine.name,
                extra={"sheet_name": sheet_ref.name},
            )
        )
        reading_order.append(block_id)

    return PageParseResult(
        page_index=page_index,
        blocks=blocks,
        tables=tables,
        reading_order=reading_order,
        confidence=confidence if blocks else 0.0,
        source_engine=ExcelTextEngine.name,
    )


def _load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    except ET.ParseError as exc:
        raise RuntimeError("Invalid Excel file: sharedStrings.xml could not be parsed.") from exc

    strings: list[str] = []
    for item in root.findall(_s("si")):
        strings.append(_text_from_text_nodes(item))
    return strings


def _extract_sheet_refs(workbook_root: ET.Element, rels_root: ET.Element) -> list[SheetRef]:
    rels = {
        rel.attrib.get("Id", ""): rel.attrib.get("Target", "")
        for rel in rels_root.findall(_pkg("Relationship"))
    }
    sheet_refs: list[SheetRef] = []
    sheets = workbook_root.find(_s("sheets"))
    if sheets is None:
        return sheet_refs

    for index, sheet in enumerate(sheets.findall(_s("sheet")), start=1):
        name = sheet.attrib.get("name") or f"Sheet{index}"
        rel_id = sheet.attrib.get(f"{{{REL_NS}}}id", "")
        target = rels.get(rel_id, "")
        if not target:
            continue
        sheet_refs.append(SheetRef(name=name, path=_workbook_target_to_archive_path(target)))
    return sheet_refs


def _workbook_target_to_archive_path(target: str) -> str:
    normalized = target.replace("\\", "/")
    if normalized.startswith("/"):
        return normalized.lstrip("/")
    return str(PurePosixPath("xl") / normalized)


def _extract_rows(sheet_root: ET.Element, shared_strings: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    max_col = 0
    sheet_data = sheet_root.find(_s("sheetData"))
    if sheet_data is None:
        return rows

    for row in sheet_data.findall(_s("row")):
        values_by_col: dict[int, str] = {}
        fallback_col = 0
        for cell in row.findall(_s("c")):
            col_index = _cell_column_index(cell.attrib.get("r"), fallback_col)
            values_by_col[col_index] = _cell_value(cell, shared_strings)
            fallback_col = col_index + 1
            max_col = max(max_col, col_index + 1)
        if values_by_col:
            row_values = [values_by_col.get(col, "") for col in range(max_col)]
            rows.append(row_values)

    if not rows:
        return []
    return [_pad_row(row, max_col) for row in rows if any(value.strip() for value in row)]


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        inline = cell.find(_s("is"))
        return _clean_text(_text_from_text_nodes(inline)) if inline is not None else ""

    raw_value = cell.findtext(_s("v"), default="")
    if cell_type == "s":
        try:
            return shared_strings[int(raw_value)]
        except (ValueError, IndexError):
            return ""
    if cell_type == "b":
        return "TRUE" if raw_value == "1" else "FALSE"
    return _clean_text(raw_value)


def _rows_to_table(rows: list[list[str]], page_index: int, confidence: float) -> Table | None:
    if not rows:
        return None

    column_count = max(len(row) for row in rows)
    cells = [
        TableCell(row=row_index, col=col_index, text=_clean_text(value), confidence=confidence)
        for row_index, row in enumerate(_pad_row(row, column_count) for row in rows)
        for col_index, value in enumerate(row)
    ]
    return Table(
        table_id=f"excel_text_tbl_p{page_index}_0",
        page_index=page_index,
        cells=cells,
        confidence=confidence,
    )


def _sheet_to_markdown(sheet_name: str, rows: list[list[str]]) -> str:
    table = _rows_to_markdown(rows)
    if not table:
        return ""
    return f"## {_escape_heading(sheet_name)}\n\n{table}"


def _escape_heading(text: str) -> str:
    return _clean_text(text).replace("#", r"\#")


def _cell_column_index(cell_ref: str | None, fallback: int) -> int:
    if not cell_ref:
        return fallback
    match = re.match(r"([A-Za-z]+)", cell_ref)
    if match is None:
        return fallback
    index = 0
    for char in match.group(1).upper():
        index = index * 26 + (ord(char) - ord("A") + 1)
    return max(0, index - 1)


def _text_from_text_nodes(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return _clean_text("".join(node.text or "" for node in element.iter() if node.tag == _s("t")))


def _s(local_name: str) -> str:
    return f"{{{SHEET_NS}}}{local_name}"


def _pkg(local_name: str) -> str:
    return f"{{{PACKAGE_REL_NS}}}{local_name}"


# =====================================================================================
# Shared helpers: LibreOffice conversion, text cleanup, markdown tables
# =====================================================================================

def _find_soffice() -> Path | None:
    for executable in ("soffice", "soffice.exe", "libreoffice", "libreoffice.exe"):
        found = shutil.which(executable)
        if found:
            return Path(found)

    for candidate in (
        Path("C:/Program Files/LibreOffice/program/soffice.exe"),
        Path("C:/Program Files (x86)/LibreOffice/program/soffice.exe"),
    ):
        if candidate.exists():
            return candidate
    return None


def _convert_office(path: Path, output_dir: Path, *, target_format: str) -> Path:
    """Convert a legacy Office file (.doc/.xls) to its modern format via LibreOffice."""
    source_ext = path.suffix.lower()
    soffice = _find_soffice()
    if soffice is None:
        raise RuntimeError(
            f"Legacy {source_ext} requires LibreOffice/soffice for conversion to .{target_format} before parsing."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(soffice),
        "--headless",
        "--convert-to",
        target_format,
        "--outdir",
        str(output_dir),
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=CONVERSION_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Legacy {source_ext} conversion timed out.") from exc
    except OSError as exc:
        raise RuntimeError(f"Legacy {source_ext} conversion could not start: {exc}") from exc
    if completed.returncode != 0:
        detail = _compact_process_output(completed.stderr or completed.stdout)
        raise RuntimeError(f"Legacy {source_ext} conversion failed: {detail}")

    expected_path = output_dir / f"{path.stem}.{target_format}"
    if expected_path.exists():
        return expected_path
    converted = list(output_dir.glob(f"*.{target_format}"))
    if converted:
        return converted[0]
    detail = _compact_process_output(completed.stderr or completed.stdout)
    raise RuntimeError(f"Legacy {source_ext} conversion did not produce a .{target_format} file: {detail}")


def _compact_process_output(message: str, max_len: int = 220) -> str:
    compact = " ".join((message or "").split())
    if len(compact) <= max_len:
        return compact or "no converter output"
    return compact[: max_len - 3] + "..."


def _clean_text(text: str) -> str:
    lines = [" ".join(line.split()) for line in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _rows_to_markdown(rows: list[list[str]]) -> str:
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        return ""

    column_count = max(len(row) for row in rows)
    normalized_rows = [_pad_row(row, column_count) for row in rows]
    header = normalized_rows[0]
    separator = ["---"] * column_count
    markdown_rows = [_markdown_row(header), _markdown_row(separator)]
    markdown_rows.extend(_markdown_row(row) for row in normalized_rows[1:])
    return "\n".join(markdown_rows)


def _markdown_row(cells: list[str]) -> str:
    return "| " + " | ".join(_escape_markdown_cell(cell) for cell in cells) + " |"


def _escape_markdown_cell(text: str) -> str:
    return _clean_text(text).replace("|", r"\|").replace("\n", "<br>")


def _pad_row(row: list[str], column_count: int) -> list[str]:
    return row + [""] * max(0, column_count - len(row))
