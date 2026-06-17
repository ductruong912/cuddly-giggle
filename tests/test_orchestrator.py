"""Orchestrator routing: which engine handles which input, and fallback behaviour.

All engines are fakes injected through the constructor, so no real OCR / GPU runs.
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.domain.schemas import ParseOptions
from app.services.orchestrator import ParseOrchestrator


def _orchestrator(**engines):
    return ParseOrchestrator(app_settings=settings, **engines)


def test_docx_routes_to_word_engine(make_fake_engine):
    word = make_fake_engine("word_text")
    primary = make_fake_engine("primary")
    orch = _orchestrator(word_text_engine=word, primary_engine=primary)

    resp = orch.parse("file.docx", ParseOptions())

    assert word.called and not primary.called
    assert resp.markdown == "# markdown"


def test_xlsx_routes_to_excel_engine(make_fake_engine):
    excel = make_fake_engine("excel_text")
    primary = make_fake_engine("primary")
    orch = _orchestrator(excel_text_engine=excel, primary_engine=primary)

    orch.parse("sheet.xlsx", ParseOptions())

    assert excel.called and not primary.called


def test_image_routes_to_primary_engine(make_fake_engine):
    primary = make_fake_engine("primary")
    word = make_fake_engine("word_text")
    orch = _orchestrator(primary_engine=primary, word_text_engine=word)

    orch.parse("scan.png", ParseOptions())

    assert primary.called and not word.called


def test_pdf_with_usable_text_skips_ocr(make_fake_engine, make_engine_result):
    pdf_text = make_fake_engine("pdf_text", result=make_engine_result("pdf_text", usable_text=True))
    primary = make_fake_engine("primary")
    orch = _orchestrator(pdf_text_engine=pdf_text, primary_engine=primary)

    resp = orch.parse("doc.pdf", ParseOptions())

    assert pdf_text.called and not primary.called
    assert "PDF text layer" in resp.decision.reason


def test_pdf_with_unusable_text_falls_to_ocr(make_fake_engine, make_engine_result):
    pdf_text = make_fake_engine(
        "pdf_text", result=make_engine_result("pdf_text", usable_text=False, markdown=None)
    )
    primary = make_fake_engine("primary")
    orch = _orchestrator(pdf_text_engine=pdf_text, primary_engine=primary)

    orch.parse("scanned.pdf", ParseOptions())

    assert pdf_text.called and primary.called


def test_pdf_text_engine_error_falls_to_ocr(make_fake_engine):
    pdf_text = make_fake_engine("pdf_text", exc=RuntimeError("PyMuPDF blew up"))
    primary = make_fake_engine("primary")
    orch = _orchestrator(pdf_text_engine=pdf_text, primary_engine=primary)

    orch.parse("doc.pdf", ParseOptions())

    assert pdf_text.called and primary.called


def test_primary_failure_uses_fallback_when_enabled(make_fake_engine):
    primary = make_fake_engine("primary", exc=RuntimeError("engine down"))
    fallback = make_fake_engine("fallback")
    orch = _orchestrator(primary_engine=primary, fallback_engine=fallback)

    resp = orch.parse("scan.png", ParseOptions(enable_fallback=True))

    assert primary.called and fallback.called
    assert "fallback" in resp.decision.reason.lower()


def test_primary_failure_raises_when_fallback_disabled(make_fake_engine):
    primary = make_fake_engine("primary", exc=RuntimeError("engine down"))
    fallback = make_fake_engine("fallback")
    orch = _orchestrator(primary_engine=primary, fallback_engine=fallback)

    with pytest.raises(RuntimeError):
        orch.parse("scan.png", ParseOptions(enable_fallback=False))
    assert not fallback.called
