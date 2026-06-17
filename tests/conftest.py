"""Shared fixtures: minimal in-memory Office files and fake parse engines.

Everything here runs on a bare clone — no GPU, models, network, or LibreOffice.
Legacy `.doc`/`.xls` and real OCR are covered separately behind skip markers.
"""
from __future__ import annotations

import zipfile

import pytest

from app.engines.base import EngineParseResult, ParseEngine
from app.domain.schemas import Block, BlockType, PageParseResult

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


# =====================================================================================
# Minimal .docx / .xlsx builders (the engines read only the few XML parts below)
# =====================================================================================

def _docx_document_xml(paragraphs: list[str], table: list[list[str]] | None) -> str:
    body: list[str] = []
    for text in paragraphs:
        body.append(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>")
    if table:
        rows = []
        for row in table:
            cells = "".join(
                f"<w:tc><w:p><w:r><w:t>{value}</w:t></w:r></w:p></w:tc>" for value in row
            )
            rows.append(f"<w:tr>{cells}</w:tr>")
        body.append(f"<w:tbl>{''.join(rows)}</w:tbl>")
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document xmlns:w="{W_NS}"><w:body>{"".join(body)}</w:body></w:document>'
    )


@pytest.fixture
def make_docx():
    """Return a factory: make_docx(path, paragraphs, table=None) -> path."""
    def _make(path, paragraphs, table=None):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml", _docx_document_xml(paragraphs, table))
        return path

    return _make


@pytest.fixture
def make_xlsx():
    """Return a factory: make_xlsx(path, sheet_name, rows) -> path.

    `rows` is a grid of strings; each cell is written as an inline string so no
    sharedStrings table is needed.
    """
    def _make(path, sheet_name, rows):
        cells_xml = []
        for r, row in enumerate(rows, start=1):
            cols = []
            for c, value in enumerate(row):
                ref = f"{chr(ord('A') + c)}{r}"
                cols.append(f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>')
            cells_xml.append(f'<row r="{r}">{"".join(cols)}</row>')
        sheet = (
            f'<?xml version="1.0"?><worksheet xmlns="{S_NS}">'
            f'<sheetData>{"".join(cells_xml)}</sheetData></worksheet>'
        )
        workbook = (
            f'<?xml version="1.0"?><workbook xmlns="{S_NS}" xmlns:r="{R_NS}">'
            f'<sheets><sheet name="{sheet_name}" r:id="rId1"/></sheets></workbook>'
        )
        rels = (
            f'<?xml version="1.0"?><Relationships xmlns="{PKG_NS}">'
            f'<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>'
        )
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("xl/workbook.xml", workbook)
            archive.writestr("xl/_rels/workbook.xml.rels", rels)
            archive.writestr("xl/worksheets/sheet1.xml", sheet)
        return path

    return _make


# =====================================================================================
# Fake engines for orchestrator / API routing tests (no real OCR)
# =====================================================================================

class FakeEngine(ParseEngine):
    """A parse engine that returns a canned result or raises, and records calls."""

    def __init__(self, name: str, result: EngineParseResult | None = None,
                exc: Exception | None = None) -> None:
        self.name = name
        self._result = result
        self._exc = exc
        self.calls: list[tuple[str, str]] = []

    def parse(self, input_path: str, lang_hint: str = "auto") -> EngineParseResult:
        self.calls.append((input_path, lang_hint))
        if self._exc is not None:
            raise self._exc
        return self._result if self._result is not None else engine_result(self.name)

    @property
    def called(self) -> bool:
        return bool(self.calls)


def engine_result(name: str = "eng", text: str = "Lorem ipsum dolor sit amet consectetur. ",
                markdown: str | None = "# markdown", usable_text: bool = True) -> EngineParseResult:
    """Build an EngineParseResult with one text page.

    With usable_text=True the text easily clears the PDF-text usability gates;
    with usable_text=False it is empty so the orchestrator must fall back to OCR.
    """
    blocks = []
    if usable_text:
        blocks = [Block(block_id="b0", type=BlockType.text,
                        content=text * 3, page_index=0, source_engine=name)]
    page = PageParseResult(page_index=0, blocks=blocks,
                        confidence=0.9 if blocks else 0.0, source_engine=name)
    return EngineParseResult(engine_name=name, pages=[page], markdown=markdown)


@pytest.fixture
def make_fake_engine():
    def _make(name, result=None, exc=None):
        return FakeEngine(name, result=result, exc=exc)

    return _make


@pytest.fixture
def make_engine_result():
    """Expose the engine_result factory to tests."""
    return engine_result
