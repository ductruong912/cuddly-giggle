from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any
import xml.etree.ElementTree as ET
import zipfile

from app.core.config import Settings, settings
from app.domain.schemas import Block, BlockType, PageParseResult, Table, TableCell
from app.services.engines.base import EngineParseResult, ParseEngine


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DOC_SUFFIXES = {".doc", ".docx"}
DOC_CONVERSION_TIMEOUT_SECONDS = 60


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
            converted_path = _convert_doc_to_docx(path, Path(temp_dir))
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
                        confidence=self.settings.word_text_confidence,
                        page_index=0,
                        source_engine=self.name,
                    )
                )
                reading_order.append(block_id)
                markdown_parts.append(text)
                block_index += 1
                continue

            if child.tag == _w("tbl"):
                rows, table = _extract_table(child, len(tables), self.settings.word_text_confidence)
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
                        confidence=self.settings.word_text_confidence,
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
            confidence=self.settings.word_text_confidence if has_content else 0.0,
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


def _convert_doc_to_docx(path: Path, output_dir: Path) -> Path:
    soffice = _find_soffice()
    if soffice is None:
        raise RuntimeError("Legacy .doc requires LibreOffice/soffice for conversion to .docx before parsing.")

    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(soffice),
        "--headless",
        "--convert-to",
        "docx",
        "--outdir",
        str(output_dir),
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=DOC_CONVERSION_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Legacy .doc conversion timed out.") from exc
    except OSError as exc:
        raise RuntimeError(f"Legacy .doc conversion could not start: {exc}") from exc
    if completed.returncode != 0:
        detail = _compact_process_output(completed.stderr or completed.stdout)
        raise RuntimeError(f"Legacy .doc conversion failed: {detail}")

    expected_path = output_dir / f"{path.stem}.docx"
    if expected_path.exists():
        return expected_path
    converted = list(output_dir.glob("*.docx"))
    if converted:
        return converted[0]
    detail = _compact_process_output(completed.stderr or completed.stdout)
    raise RuntimeError(f"Legacy .doc conversion did not produce a .docx file: {detail}")


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


def _rows_to_markdown(rows: list[list[str]]) -> str:
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        return ""

    column_count = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]
    header = normalized_rows[0]
    separator = ["---"] * column_count
    markdown_rows = [_markdown_row(header), _markdown_row(separator)]
    markdown_rows.extend(_markdown_row(row) for row in normalized_rows[1:])
    return "\n".join(markdown_rows)


def _markdown_row(cells: list[str]) -> str:
    return "| " + " | ".join(_escape_markdown_cell(cell) for cell in cells) + " |"


def _escape_markdown_cell(text: str) -> str:
    return _clean_text(text).replace("|", r"\|").replace("\n", "<br>")


def _clean_text(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _compact_process_output(message: str, max_len: int = 220) -> str:
    compact = " ".join((message or "").split())
    if len(compact) <= max_len:
        return compact or "no converter output"
    return compact[: max_len - 3] + "..."


def _w(local_name: str) -> str:
    return f"{{{W_NS}}}{local_name}"
