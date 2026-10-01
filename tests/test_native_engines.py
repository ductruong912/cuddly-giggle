"""The PDF text-layer path: encoding repair, and deciding when to skip OCR.

Fixtures are generated rather than committed, so the suite needs no sample
documents. PyMuPDF is a hard dependency of the parser under test.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from config.config import settings
from core.domain.schemas import Block, BlockType, PageParseResult
from core.engines.base import EngineParseResult
from core.engines.native import (
    PdfTextEngine,
    is_pdf_text_result_usable,
    repair_legacy_vietnamese_text,
)

fitz = pytest.importorskip("fitz", reason="PyMuPDF is required to build PDF fixtures")


SECOND_PAGE_NOTE = (
    "Trang hai: ghi chu giao hang tai kho Ha Noi, lien he bo phan mua hang "
    "truoc khi giao de xac nhan so luong va thoi gian nhan hang."
)


def build_pdf(path: Path, *, second_page_text: str) -> Path:
    """A two-page PDF with a real text layer and a crude three-column table."""
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 100), "HOA DON MUA HANG", fontsize=16)
    page.insert_text((72, 130), "So PO: 215497-000 OI ngay 05 thang 06 nam 2026", fontsize=11)
    rows = [
        ("Ma hang", "So luong", "Don gia"),
        ("TT-0012", "4", "125000"),
        ("TT-0099", "11", "98000"),
        ("TT-1234", "2", "1450000"),
    ]
    y = 170
    for code, quantity, price in rows:
        page.insert_text((72, y), code, fontsize=10)
        page.insert_text((220, y), quantity, fontsize=10)
        page.insert_text((360, y), price, fontsize=10)
        y += 22
    second = document.new_page()
    second.insert_text((72, 100), second_page_text, fontsize=11)
    document.save(str(path))
    document.close()
    return path


@pytest.fixture
def text_pdf(tmp_path: Path) -> Path:
    return build_pdf(tmp_path / "purchase_order.pdf", second_page_text=SECOND_PAGE_NOTE)


def result_with(text: str, pages: int = 1) -> EngineParseResult:
    """Wrap raw text as an engine result, for the usability heuristics."""
    return EngineParseResult(
        engine_name="test",
        pages=[
            PageParseResult(
                page_index=index,
                blocks=[
                    Block(
                        block_id=f"b{index}",
                        type=BlockType.text,
                        content=text,
                        page_index=index,
                    )
                ],
            )
            for index in range(pages)
        ],
        raw={},
    )


# -- encoding repair ---------------------------------------------------------

def test_legacy_text_is_converted() -> None:
    """TCVN3 uses codepoints correct Vietnamese never does; those identify it."""
    legacy = "Ngµy giao hµng"

    assert repair_legacy_vietnamese_text(legacy) != legacy


def test_correct_unicode_is_left_alone() -> None:
    """The regression this guards: 'Nguyên Văn' was being rewritten to 'Nguyờn Văn'.

    Letters like 'ê' sit on both sides of the TCVN3 table, so treating them as
    markers corrupts text that was already correct.
    """
    for text in ("Nguyên Văn", "Tiếng Việt", "Địa chỉ"):
        assert repair_legacy_vietnamese_text(text) == text


@pytest.mark.parametrize("text", ["", "plain ascii", "PO 215497", "123.456"])
def test_text_without_markers_is_untouched(text: str) -> None:
    assert repair_legacy_vietnamese_text(text) == text


# -- usability heuristics ----------------------------------------------------

READABLE_PAGE = (
    "Hoa don mua hang so 215497 ngay 05 thang 06 nam 2026, giao tai kho Ha Noi. "
    "Ma hang TT-0012 so luong 4 don gia 125000. Ma hang TT-0099 so luong 11 "
    "don gia 98000. Tong cong thanh tien da bao gom thue gia tri gia tang."
)


def test_a_readable_text_layer_is_usable() -> None:
    assert is_pdf_text_result_usable(result_with(READABLE_PAGE)) is True


def test_every_page_must_carry_text() -> None:
    """The ratio is 1.0: one near-empty page sends the whole document to OCR.

    A cover sheet or a scanned annex mixed into a digital PDF is exactly the
    case this catches, and reading half a document is worse than reading none.
    """
    result = result_with(READABLE_PAGE, pages=2)
    result.pages[1].blocks[0].content = "Trang 2"

    assert is_pdf_text_result_usable(result) is False


def test_an_empty_result_is_not_usable() -> None:
    assert is_pdf_text_result_usable(EngineParseResult(engine_name="test", pages=[])) is False


def test_a_sparse_text_layer_is_not_usable() -> None:
    """Too few characters means a scan with stray marks, not a text layer."""
    assert is_pdf_text_result_usable(result_with("PO 1")) is False


def test_a_garbled_text_layer_falls_back_to_ocr() -> None:
    """Private-use codepoints mean an undecodable embedded font."""
    garbled = "".join(chr(0xE000 + index % 100) for index in range(400))

    assert is_pdf_text_result_usable(result_with(garbled)) is False


def test_a_broken_font_cmap_falls_back_to_ocr() -> None:
    """Digits substituted mid-word ('Nguy6n') decode as valid but wrong letters."""
    corrupt = " ".join(["Nguy6n", "Tr4n", "Ph5m", "H0ang", "L3", "V0", "D1nh", "B9i"] * 8)

    assert is_pdf_text_result_usable(result_with(corrupt)) is False


# -- the engine end to end ---------------------------------------------------

def test_the_engine_reads_a_real_text_layer(text_pdf: Path) -> None:
    result = PdfTextEngine(settings).parse(str(text_pdf))

    assert len(result.pages) == 2
    combined = "\n".join(
        block.content for page in result.pages for block in page.blocks
    )
    assert "HOA DON MUA HANG" in combined
    assert "TT-0012" in combined
    assert "Trang hai" in combined
    assert is_pdf_text_result_usable(result) is True
    first_page = "\n".join(block.content for block in result.pages[0].blocks)
    for code in ("TT-0012", "TT-0099", "TT-1234"):
        assert code in first_page


def test_a_document_with_one_sparse_page_falls_back_to_ocr(tmp_path: Path) -> None:
    """End to end: the strict all-pages rule applies to a real file, not just a stub."""
    sparse = build_pdf(tmp_path / "sparse.pdf", second_page_text="Trang 2")

    assert is_pdf_text_result_usable(PdfTextEngine(settings).parse(str(sparse))) is False
