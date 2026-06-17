"""Native text engines: .docx / .xlsx parsing, the PDF text engine, and the legacy
.doc / .xls conversion path (the last two need LibreOffice and are skipped without it).
"""
from __future__ import annotations

import subprocess

import pytest

from app.engines.native import (
    ExcelTextEngine,
    PdfTextEngine,
    WordTextEngine,
    _find_soffice,
    is_pdf_text_result_usable,
)

needs_soffice = pytest.mark.skipif(_find_soffice() is None, reason="LibreOffice/soffice not installed")


# =====================================================================================
# Word (.docx)
# =====================================================================================

class TestWordDocx:
    def test_extracts_paragraphs_and_table(self, tmp_path, make_docx):
        path = make_docx(
            tmp_path / "doc.docx",
            paragraphs=["Tiêu đề tài liệu", "Đoạn nội dung thứ hai."],
            table=[["Tên", "Giá"], ["Cà phê", "25000"]],
        )
        result = WordTextEngine().parse(str(path))

        assert result.raw["paragraph_count"] == 2
        assert result.raw["table_count"] == 1
        assert "Tiêu đề tài liệu" in result.markdown
        assert "| Tên | Giá |" in result.markdown
        assert "| Cà phê | 25000 |" in result.markdown

    def test_invalid_docx_raises(self, tmp_path):
        path = tmp_path / "broken.docx"
        path.write_bytes(b"not a zip")
        with pytest.raises(RuntimeError):
            WordTextEngine().parse(str(path))


# =====================================================================================
# Excel (.xlsx)
# =====================================================================================

class TestExcelXlsx:
    def test_renders_sheet_as_markdown_table(self, tmp_path, make_xlsx):
        path = make_xlsx(
            tmp_path / "book.xlsx",
            sheet_name="Doanh thu",
            rows=[["STT", "Sản phẩm", "Thành tiền"], ["1", "Trà đào", "150000"]],
        )
        result = ExcelTextEngine().parse(str(path))

        assert result.raw["parsed_sheet_count"] == 1
        assert "## Doanh thu" in result.markdown
        assert "| STT | Sản phẩm | Thành tiền |" in result.markdown
        assert "| 1 | Trà đào | 150000 |" in result.markdown

    def test_empty_sheet_produces_no_pages(self, tmp_path, make_xlsx):
        path = make_xlsx(tmp_path / "empty.xlsx", sheet_name="Blank", rows=[])
        assert ExcelTextEngine().parse(str(path)).pages == []


# =====================================================================================
# PDF text engine (needs PyMuPDF, no GPU)
# =====================================================================================

class TestPdfTextEngine:
    def test_born_digital_text_is_extracted_and_usable(self, tmp_path):
        fitz = pytest.importorskip("fitz", reason="PyMuPDF not installed")
        text = ("Day la mot tai lieu PDF co san lop van ban day du. "
                "Noi dung du dai de vuot nguong ky tu toi thieu cua bo loc kiem tra.")
        path = tmp_path / "born_digital.pdf"
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), text)
        doc.save(str(path))
        doc.close()

        result = PdfTextEngine().parse(str(path))
        assert "tai lieu PDF" in (result.markdown or "")
        assert is_pdf_text_result_usable(result) is True

    def test_non_pdf_path_returns_empty(self, tmp_path):
        path = tmp_path / "note.txt"
        path.write_text("hello", encoding="utf-8")
        assert PdfTextEngine().parse(str(path)).pages == []


# =====================================================================================
# Legacy .doc / .xls — require LibreOffice
# =====================================================================================

@needs_soffice
def test_legacy_doc_is_converted_and_parsed(tmp_path):
    src = tmp_path / "src.txt"
    src.write_text("Legacy doc content here", encoding="utf-8")
    subprocess.run(
        [str(_find_soffice()), "--headless", "--convert-to", "doc", "--outdir", str(tmp_path), str(src)],
        capture_output=True, timeout=90, check=True,
    )
    result = WordTextEngine().parse(str(tmp_path / "src.doc"))
    assert "Legacy doc content here" in (result.markdown or "")
    assert result.raw["source_suffix"] == ".doc"


@needs_soffice
def test_legacy_xls_is_converted_and_parsed(tmp_path):
    csv = tmp_path / "data.csv"
    csv.write_text("Name,Qty\nApple,10\nPear,5\n", encoding="utf-8")
    subprocess.run(
        [str(_find_soffice()), "--headless", "--convert-to", "xls", "--outdir", str(tmp_path), str(csv)],
        capture_output=True, timeout=90, check=True,
    )
    result = ExcelTextEngine().parse(str(tmp_path / "data.xls"))
    assert "| Name | Qty |" in (result.markdown or "")
    assert result.raw["source_suffix"] == ".xls"
