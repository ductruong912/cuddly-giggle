"""PDF text-layer usability detection — the gate that decides native text vs OCR.

These assert on EngineParseResult objects built by hand, so no PDF file or PyMuPDF
is needed. They mirror the real-document behaviour found while tuning the thresholds:
clean born-digital text is kept, while empty / sparse / undecodable / broken-font
(wrong-but-valid Latin) layers are rejected so the document falls to OCR.
"""
from __future__ import annotations

from app.engines.base import EngineParseResult
from app.domain.schemas import Block, BlockType, PageParseResult
from app.engines.native import (
    is_pdf_text_result_usable,
    _corrupt_word_ratio,
    _readable_char_ratio,
    repair_legacy_vietnamese_text,
)


def _result(*page_texts: str) -> EngineParseResult:
    pages = []
    for i, text in enumerate(page_texts):
        blocks = []
        if text:
            blocks = [Block(block_id=f"b{i}", type=BlockType.text, content=text, page_index=i)]
        pages.append(PageParseResult(page_index=i, blocks=blocks,
                                    confidence=0.98 if blocks else 0.0))
    return EngineParseResult(engine_name="pdf_text", pages=pages)


GOOD_VI = ("Cộng hòa xã hội chủ nghĩa Việt Nam, độc lập tự do hạnh phúc. "
            "Hôm nay chúng tôi lập biên bản bàn giao tài liệu theo quy định hiện hành.")
GOOD_EN = "The quick brown fox jumps over the lazy dog near the riverbank. " * 2
# Broken font that maps glyphs onto valid-but-wrong Latin with digits wedged in words.
BROKEN_FONT = " ".join(["Nguy6n", "ph6p", "gi6p", "b6n", "ch6u", "tr6ch"] * 6)
PUA_GARBAGE = "".join(chr(0xE000 + (i % 200)) for i in range(120))
REPLACEMENT_GARBAGE = "�" * 120


class TestIsPdfTextResultUsable:
    def test_clean_vietnamese_text_is_usable(self):
        assert is_pdf_text_result_usable(_result(GOOD_VI)) is True

    def test_clean_english_multipage_is_usable(self):
        assert is_pdf_text_result_usable(_result(GOOD_EN, GOOD_EN)) is True

    def test_no_pages_is_not_usable(self):
        assert is_pdf_text_result_usable(_result()) is False

    def test_empty_pages_are_not_usable(self):
        assert is_pdf_text_result_usable(_result("", "")) is False

    def test_one_image_page_rejects_whole_document(self):
        # All-or-nothing: a single text-less (scanned) page sends the doc to OCR.
        assert is_pdf_text_result_usable(_result(GOOD_VI, "")) is False

    def test_too_few_total_chars_is_not_usable(self):
        assert is_pdf_text_result_usable(_result("Hóa đơn 01")) is False

    def test_broken_font_digit_in_word_is_not_usable(self):
        assert is_pdf_text_result_usable(_result(BROKEN_FONT)) is False

    def test_private_use_area_glyphs_are_not_usable(self):
        assert is_pdf_text_result_usable(_result(PUA_GARBAGE)) is False

    def test_replacement_characters_are_not_usable(self):
        assert is_pdf_text_result_usable(_result(REPLACEMENT_GARBAGE)) is False


class TestReadableCharRatio:
    def test_plain_text_is_fully_readable(self):
        assert _readable_char_ratio("Hello world 123") == 1.0

    def test_private_use_area_is_unreadable(self):
        assert _readable_char_ratio(PUA_GARBAGE) == 0.0

    def test_replacement_char_is_unreadable(self):
        assert _readable_char_ratio(REPLACEMENT_GARBAGE) == 0.0

    def test_empty_text_is_zero(self):
        assert _readable_char_ratio("   ") == 0.0


class TestCorruptWordRatio:
    def test_clean_prose_has_no_corrupt_words(self):
        ratio, count = _corrupt_word_ratio(GOOD_EN)
        assert count > 0
        assert ratio == 0.0

    def test_broken_font_words_are_flagged(self):
        ratio, count = _corrupt_word_ratio(BROKEN_FONT)
        assert count >= 20
        assert ratio > 0.07

    def test_numeric_tokens_as_separate_words_are_not_corrupt(self):
        # Dates / amounts in their own tokens (not wedged inside a word) must not be
        # flagged as broken-font corruption.
        ratio, _ = _corrupt_word_ratio("Ngày 08 tháng 05 năm 2026 số tiền 2587537 đồng")
        assert ratio == 0.0


class TestRepairLegacyVietnameseText:
    def test_tcvn3_is_converted_to_unicode(self):
        source = "C«ng hßa"  # contains TCVN3 marker bytes
        repaired = repair_legacy_vietnamese_text(source)
        assert repaired != source
        assert _readable_char_ratio(repaired) == 1.0

    def test_plain_text_is_unchanged(self):
        assert repair_legacy_vietnamese_text("Hello") == "Hello"

    def test_repaired_tcvn3_is_readable(self):
        repaired = repair_legacy_vietnamese_text("Th«ng tin")
        assert _readable_char_ratio(repaired) == 1.0
