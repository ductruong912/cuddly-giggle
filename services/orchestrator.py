from __future__ import annotations

import itertools
import logging
from pathlib import Path
import time
import uuid

from config.config import Settings, settings
from config.pipeline_logging import pipeline_message
from core.domain.schemas import ParseDecision, ParseResponse
from core.engines.base import EngineParseResult, ParseEngine
from core.engines.native import (
    ExcelTextEngine,
    PdfTextEngine,
    WordTextEngine,
    is_pdf_text_result_usable,
)
from services.local_ocr_selector import LocalOCRSelector
from services.output import filter_tables_markdown


logger = logging.getLogger(__name__)


class DocumentTooLarge(Exception):
    """The document has more pages than the OCR path is allowed to process."""


class ParseOrchestrator:
    def __init__(
        self,
        app_settings: Settings = settings,
        primary_engine: ParseEngine | None = None,
        pdf_text_engine: ParseEngine | None = None,
        word_text_engine: ParseEngine | None = None,
        excel_text_engine: ParseEngine | None = None,
    ) -> None:
        self.settings = app_settings
        self.primary_engine = primary_engine or LocalOCRSelector(self.settings).select()
        self.pdf_text_engine = pdf_text_engine or PdfTextEngine(self.settings)
        self.word_text_engine = word_text_engine or WordTextEngine(self.settings)
        self.excel_text_engine = excel_text_engine or ExcelTextEngine(self.settings)

    def parse(
        self,
        input_path: str,
        *,
        request_id: str | None = None,
    ) -> ParseResponse:
        """Route the file to the cheapest engine that can read it, then normalize."""
        resolved_request_id = request_id or f"req_{uuid.uuid4().hex[:12]}"
        return self._parse(input_path, resolved_request_id)

    def _parse(self, input_path: str, request_id: str) -> ParseResponse:
        total_start = time.perf_counter()
        primary_elapsed = 0.0
        pdf_text_elapsed = 0.0
        word_text_elapsed = 0.0
        excel_text_elapsed = 0.0

        if self._should_try_word_text(input_path):
            logger.info(pipeline_message("PHASE 1", "route=word_text"))
            stage_start = time.perf_counter()
            word_text = self.word_text_engine.parse(input_path)
            word_text_elapsed = time.perf_counter() - stage_start
            decision = self._build_decision()
            response = self._build_response(request_id, word_text, decision)
            logger.info(
                "parse timings request_id=%s word_text=%.3fs total=%.3fs word_text_score=%.3f",
                request_id,
                word_text_elapsed,
                time.perf_counter() - total_start,
                word_text.page_confidence,
            )
            return response

        if self._should_try_excel_text(input_path):
            logger.info(pipeline_message("PHASE 1", "route=excel_text"))
            stage_start = time.perf_counter()
            excel_text = self.excel_text_engine.parse(input_path)
            excel_text_elapsed = time.perf_counter() - stage_start
            decision = self._build_decision()
            response = self._build_response(request_id, excel_text, decision)
            logger.info(
                "parse timings request_id=%s excel_text=%.3fs total=%.3fs excel_text_score=%.3f",
                request_id,
                excel_text_elapsed,
                time.perf_counter() - total_start,
                excel_text.page_confidence,
            )
            return response

        if self._should_try_pdf_text(input_path):
            logger.info(pipeline_message("PHASE 1", "route=pdf_text"))
            try:
                stage_start = time.perf_counter()
                pdf_text = self.pdf_text_engine.parse(input_path)
                pdf_text_elapsed = time.perf_counter() - stage_start
                if is_pdf_text_result_usable(pdf_text):
                    decision = ParseDecision(reason="PDF text layer parsed without OCR.")
                    response = self._build_response(request_id, pdf_text, decision)
                    logger.info(
                        "parse timings request_id=%s pdf_text=%.3fs total=%.3fs pdf_text_score=%.3f",
                        request_id,
                        pdf_text_elapsed,
                        time.perf_counter() - total_start,
                        pdf_text.page_confidence,
                    )
                    return response
                logger.info(pipeline_message("PHASE 1", "pdf_text result=too_sparse; route=ocr"))
            except Exception as exc:
                pdf_text_elapsed = time.perf_counter() - stage_start
                logger.warning(
                    pipeline_message("PHASE 1", "pdf_text failed; route=ocr error=%s"),
                    self._compact_error(str(exc)),
                )

        self._guard_ocr_page_count(input_path)
        logger.info(pipeline_message("PHASE 1", "route=ocr engine=%s"), self.primary_engine.name)
        stage_start = time.perf_counter()
        result = self.primary_engine.parse(input_path)
        primary_elapsed = time.perf_counter() - stage_start
        decision = self._build_decision()

        response = self._build_response(request_id, result, decision)
        logger.info(
            pipeline_message(
                "PHASE 2",
                "ocr completed pages=%s blocks=%s tables=%s markdown_chars=%s duration=%.3fs total=%.3fs",
            ),
            len(response.pages),
            len(response.blocks),
            len(response.tables),
            len(response.markdown or ""),
            primary_elapsed,
            time.perf_counter() - total_start,
        )
        return response

    def _guard_ocr_page_count(self, input_path: str) -> None:
        """Reject PDFs too long to OCR before they occupy an OCR slot for an hour.

        Only the OCR path is capped: the native text engines are fast even on long
        documents, and their output is already bounded by LLM_MAX_INPUT_CHARS.
        """
        if Path(input_path).suffix.lower() != ".pdf":
            return
        try:
            # pyrefly: ignore [missing-import]
            import fitz  # PyMuPDF

            with fitz.open(input_path) as document:
                page_count = document.page_count
        except Exception:
            logger.warning("could not read the PDF page count; skipping the page cap", exc_info=True)
            return

        if page_count > self.settings.pdf_max_pages:
            raise DocumentTooLarge(
                f"This PDF has {page_count} pages; the OCR path accepts at most "
                f"{self.settings.pdf_max_pages}. Split the document or raise PDF_MAX_PAGES."
            )

    def _should_try_pdf_text(self, input_path: str) -> bool:
        return self.settings.pdf_text_parse_enabled and Path(input_path).suffix.lower() == ".pdf"

    def _should_try_word_text(self, input_path: str) -> bool:
        return Path(input_path).suffix.lower() in {".doc", ".docx"}

    def _should_try_excel_text(self, input_path: str) -> bool:
        return Path(input_path).suffix.lower() in {".xls", ".xlsx", ".xlsm"}

    def _build_response(
        self,
        request_id: str,
        result: EngineParseResult,
        decision: ParseDecision,
    ) -> ParseResponse:
        pages = result.pages
        blocks = list(itertools.chain.from_iterable(page.blocks for page in pages))
        tables = list(itertools.chain.from_iterable(page.tables for page in pages))
        reading_order = list(itertools.chain.from_iterable(page.reading_order for page in pages))

        markdown = result.markdown
        if self.settings.table_only_output:
            markdown = filter_tables_markdown(markdown)

        return ParseResponse(
            request_id=request_id,
            decision=decision,
            pages=pages,
            blocks=blocks,
            tables=tables,
            reading_order=reading_order,
            markdown=markdown,
        )

    @staticmethod
    def _build_decision(reason: str = "Parse completed.") -> ParseDecision:
        return ParseDecision(reason=reason)

    @staticmethod
    def _compact_error(message: str, max_len: int = 220) -> str:
        compact = " ".join((message or "").split())
        if len(compact) <= max_len:
            return compact
        return compact[: max_len - 3] + "..."
