from __future__ import annotations

import itertools
import logging
from pathlib import Path
import threading
import time
import uuid

from app.core.config import Settings, settings
from app.core.pipeline_logging import pipeline_message, request_logging_context
from app.domain.schemas import ParseDecision, ParseOptions, ParseResponse
from app.engines.base import EngineParseResult, ParseEngine
from app.engines.native import (
    ExcelTextEngine,
    PdfTextEngine,
    WordTextEngine,
    is_pdf_text_result_usable,
)
from app.engines.registry import create_engine
from app.services.output import filter_tables_markdown


logger = logging.getLogger(__name__)


class ParseOrchestrator:
    def __init__(
        self,
        app_settings: Settings = settings,
        primary_engine: ParseEngine | None = None,
        fallback_engine: ParseEngine | None = None,
        pdf_text_engine: ParseEngine | None = None,
        word_text_engine: ParseEngine | None = None,
        excel_text_engine: ParseEngine | None = None,
    ) -> None:
        self.settings = app_settings
        self.primary_engine = primary_engine or create_engine(self.settings.primary_engine, self.settings)
        self._fallback_engine = fallback_engine
        self._fallback_engine_lock = threading.Lock()
        self.pdf_text_engine = pdf_text_engine or PdfTextEngine(self.settings)
        self.word_text_engine = word_text_engine or WordTextEngine(self.settings)
        self.excel_text_engine = excel_text_engine or ExcelTextEngine(self.settings)

    def parse(
        self,
        input_path: str,
        options: ParseOptions,
        *,
        request_id: str | None = None,
    ) -> ParseResponse:
        resolved_request_id = request_id or f"req_{uuid.uuid4().hex[:12]}"
        with request_logging_context(resolved_request_id):
            return self._parse(input_path, options, resolved_request_id)

    def _parse(self, input_path: str, options: ParseOptions, request_id: str) -> ParseResponse:
        total_start = time.perf_counter()
        primary_elapsed = 0.0
        fallback_elapsed = 0.0
        pdf_text_elapsed = 0.0
        word_text_elapsed = 0.0
        excel_text_elapsed = 0.0

        if self._should_try_word_text(input_path):
            logger.info(pipeline_message("PHASE 1", "route=word_text"))
            stage_start = time.perf_counter()
            word_text = self.word_text_engine.parse(input_path, options.lang_hint.value)
            word_text_elapsed = time.perf_counter() - stage_start
            decision = self._build_decision()
            response = self._build_response(request_id, word_text, options, decision)
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
            excel_text = self.excel_text_engine.parse(input_path, options.lang_hint.value)
            excel_text_elapsed = time.perf_counter() - stage_start
            decision = self._build_decision()
            response = self._build_response(request_id, excel_text, options, decision)
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
                pdf_text = self.pdf_text_engine.parse(input_path, options.lang_hint.value)
                pdf_text_elapsed = time.perf_counter() - stage_start
                if is_pdf_text_result_usable(pdf_text):
                    decision = ParseDecision(reason="PDF text layer parsed without OCR.")
                    response = self._build_response(request_id, pdf_text, options, decision)
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

        try:
            logger.info(pipeline_message("PHASE 1", "route=ocr engine=%s"), self.primary_engine.name)
            stage_start = time.perf_counter()
            result = self.primary_engine.parse(input_path, options.lang_hint.value)
            primary_elapsed = time.perf_counter() - stage_start
            primary_score = result.page_confidence
            decision = self._build_decision()
        except Exception as exc:
            primary_elapsed = time.perf_counter() - stage_start
            primary_score = 0.0
            primary_error = self._compact_error(str(exc))
            if not options.enable_fallback:
                raise
            logger.warning(
                pipeline_message("PHASE 2", "primary engine=%s failed; trying fallback error=%s"),
                self.primary_engine.name,
                primary_error,
            )
            try:
                logger.info(pipeline_message("PHASE 2", "fallback started engine=%s"), self.settings.fallback_engine)
                stage_start = time.perf_counter()
                result = self._get_fallback_engine().parse(input_path, options.lang_hint.value)
                fallback_elapsed = time.perf_counter() - stage_start
            except Exception as fallback_exc:
                fallback_elapsed = time.perf_counter() - stage_start
                fallback_error = self._compact_error(str(fallback_exc))
                logger.error(pipeline_message("PHASE 2", "fallback engine failed error=%s"), fallback_error, exc_info=True)
                raise RuntimeError(
                    f"Primary engine failed: {primary_error}; fallback engine failed: {fallback_error}"
                ) from fallback_exc
            decision = self._build_decision(f"Parse completed via fallback after primary failed: {primary_error}")

        response = self._build_response(request_id, result, options, decision)
        logger.info(
            pipeline_message(
                "PHASE 2",
                "ocr completed pages=%s blocks=%s tables=%s markdown_chars=%s duration=%.3fs total=%.3fs",
            ),
            len(response.pages),
            len(response.blocks),
            len(response.tables),
            len(response.markdown or ""),
            primary_elapsed + fallback_elapsed,
            time.perf_counter() - total_start,
        )
        return response

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
        options: ParseOptions,
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

    def _get_fallback_engine(self) -> ParseEngine:
        with self._fallback_engine_lock:
            if self._fallback_engine is None:
                self._fallback_engine = create_engine(self.settings.fallback_engine, self.settings)
            return self._fallback_engine

    @staticmethod
    def _compact_error(message: str, max_len: int = 220) -> str:
        compact = " ".join((message or "").split())
        if len(compact) <= max_len:
            return compact
        return compact[: max_len - 3] + "..."
