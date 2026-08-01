"""Native document text extraction engines (PDF / Word / Excel).

Each engine reads a document's existing text layer without OCR. The Word and
Excel engines share the LibreOffice conversion path (legacy .doc/.xls) and the
Markdown-table helpers in ``office_shared``.
"""
from __future__ import annotations

from core.engines.native.excel_text import EXCEL_TEXT_CONFIDENCE, ExcelTextEngine
from core.engines.native.office_shared import CONVERSION_TIMEOUT_SECONDS
from core.engines.native.pdf_text import (
    PDF_TEXT_CONFIDENCE,
    PdfTextEngine,
    is_pdf_text_result_usable,
    repair_legacy_vietnamese_text,
)
from core.engines.native.word_text import WORD_TEXT_CONFIDENCE, WordTextEngine


__all__ = [
    "CONVERSION_TIMEOUT_SECONDS",
    "EXCEL_TEXT_CONFIDENCE",
    "ExcelTextEngine",
    "PDF_TEXT_CONFIDENCE",
    "PdfTextEngine",
    "WORD_TEXT_CONFIDENCE",
    "WordTextEngine",
    "is_pdf_text_result_usable",
    "repair_legacy_vietnamese_text",
]
