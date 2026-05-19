from __future__ import annotations

from app.domain.schemas import Block, BlockType, Point, Table, TableCell
from app.services.vietnamese_postprocess import postprocess_blocks, postprocess_markdown, postprocess_tables


def test_vietnamese_unicode_and_numeric_cleanup() -> None:
    blocks = [
        Block(
            block_id="b1",
            type=BlockType.text,
            content="  Ma so thue  0102030405  ",
            bbox=[Point(x=0, y=0)],
            confidence=0.8,
            page_index=0,
            source_engine="test",
        ),
        Block(
            block_id="b2",
            type=BlockType.text,
            content="ngay 12-01-2026",
            bbox=[Point(x=0, y=0)],
            confidence=0.8,
            page_index=0,
            source_engine="test",
        ),
    ]
    result = postprocess_blocks(blocks)
    assert "12/01/2026" in result[1].content


def test_table_cleanup_keeps_cells() -> None:
    tables = [
        Table(
            table_id="t1",
            page_index=0,
            confidence=0.7,
            cells=[TableCell(row=0, col=0, text=" 1.000.000VN\u00c4\u0090 ")],
        )
    ]
    result = postprocess_tables(tables)
    assert result[0].cells[0].text == "1.000.000 VN\u0110"


def test_mojibake_and_vietnamese_phrase_restore() -> None:
    markdown = "Luu Y: - Ncc vui long giao hang va xu\u00e1\u00ba\u00a5t hoa don theo tung don hang."
    result = postprocess_markdown(markdown)
    assert result is not None
    assert "L\u01b0u \u00dd" in result
    assert "NCC vui l\u00f2ng giao h\u00e0ng v\u00e0 xu\u1ea5t h\u00f3a \u0111\u01a1n" in result
    assert "t\u1eebng \u0111\u01a1n h\u00e0ng" in result


def test_vietnamese_address_restore() -> None:
    block = Block(
        block_id="b3",
        type=BlockType.text,
        content="SO 163, DUONG PHAN DANG LUU, PHUONG CAU KIEU, HO CHI MINH, VIET NAM",
        bbox=[Point(x=0, y=0)],
        confidence=0.8,
        page_index=0,
        source_engine="test",
    )
    result = postprocess_blocks([block])
    assert "S\u1ed0 163" in result[0].content
    assert "\u0110\u01af\u1edcNG PHAN \u0110\u0102NG L\u01afU" in result[0].content
    assert "PH\u01af\u1edcNG C\u1ea6U KI\u1ec6U" in result[0].content
    assert "H\u1ed2 CH\u00cd MINH" in result[0].content
