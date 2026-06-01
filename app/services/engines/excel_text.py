from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
from typing import Any
import xml.etree.ElementTree as ET
import zipfile

from app.core.config import Settings, settings
from app.domain.schemas import Block, BlockType, PageParseResult, Table, TableCell
from app.services.engines.base import EngineParseResult, ParseEngine


SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
EXCEL_SUFFIXES = {".xls", ".xlsx", ".xlsm"}
XLS_CONVERSION_TIMEOUT_SECONDS = 60


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
            converted_path = _convert_xls_to_xlsx(path, Path(temp_dir))
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
                pages = [_parse_sheet(archive, sheet_ref, index, shared_strings, self.settings.excel_text_confidence)
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


def _escape_heading(text: str) -> str:
    return _clean_text(text).replace("#", r"\#")


def _pad_row(row: list[str], column_count: int) -> list[str]:
    return row + [""] * max(0, column_count - len(row))


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


def _convert_xls_to_xlsx(path: Path, output_dir: Path) -> Path:
    soffice = _find_soffice()
    if soffice is None:
        raise RuntimeError("Legacy .xls requires LibreOffice/soffice for conversion to .xlsx before parsing.")

    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(soffice),
        "--headless",
        "--convert-to",
        "xlsx",
        "--outdir",
        str(output_dir),
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=XLS_CONVERSION_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Legacy .xls conversion timed out.") from exc
    except OSError as exc:
        raise RuntimeError(f"Legacy .xls conversion could not start: {exc}") from exc

    if completed.returncode != 0:
        detail = _compact_process_output(completed.stderr or completed.stdout)
        raise RuntimeError(f"Legacy .xls conversion failed: {detail}")

    expected_path = output_dir / f"{path.stem}.xlsx"
    if expected_path.exists():
        return expected_path
    converted = list(output_dir.glob("*.xlsx"))
    if converted:
        return converted[0]
    detail = _compact_process_output(completed.stderr or completed.stdout)
    raise RuntimeError(f"Legacy .xls conversion did not produce a .xlsx file: {detail}")


def _clean_text(text: str) -> str:
    lines = [" ".join(line.split()) for line in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _compact_process_output(message: str, max_len: int = 220) -> str:
    compact = " ".join((message or "").split())
    if len(compact) <= max_len:
        return compact or "no converter output"
    return compact[: max_len - 3] + "..."


def _s(local_name: str) -> str:
    return f"{{{SHEET_NS}}}{local_name}"


def _pkg(local_name: str) -> str:
    return f"{{{PACKAGE_REL_NS}}}{local_name}"
