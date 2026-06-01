from __future__ import annotations

import itertools
import logging
from pathlib import Path
import time
import uuid

from app.core.config import Settings, settings
from app.domain.schemas import OutputFormat, PageParseResult, ParseDecision, ParseOptions, ParseResponse
from app.services.engines.base import EngineParseResult, ParseEngine
from app.services.engines.pdf_text import PdfTextEngine, is_pdf_text_result_usable
from app.services.engines.registry import create_engine
from app.services.merge import merge_results
from app.services.quality import QualityAssessment, assess_document_quality
from app.services.qwen_verifier import QwenVerifier


logger = logging.getLogger(__name__)


class ParseOrchestrator:
    def __init__(
        self,
        app_settings: Settings = settings,
        primary_engine: ParseEngine | None = None,
        fallback_engine: ParseEngine | None = None,
        pdf_text_engine: ParseEngine | None = None,
    ) -> None:
        self.settings = app_settings
        self.primary_engine = primary_engine or create_engine(self.settings.primary_engine, self.settings)
        self.fallback_engine = fallback_engine or create_engine(self.settings.fallback_engine, self.settings)
        self.pdf_text_engine = pdf_text_engine or PdfTextEngine(self.settings)
        self.verifier = None
        if self.settings.qwen_verifier_enabled:
            self.verifier = QwenVerifier(
                base_url=self.settings.qwen_verifier_base_url,
                model=self.settings.qwen_verifier_model,
                api_key=self.settings.qwen_verifier_api_key,
                timeout_seconds=self.settings.qwen_verifier_timeout_seconds,
                chat_path=self.settings.qwen_verifier_chat_path,
            )

    def parse(self, input_path: str, options: ParseOptions) -> ParseResponse:
        total_start = time.perf_counter()
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        quality_elapsed = 0.0
        primary_elapsed = 0.0
        fallback_elapsed = 0.0
        pdf_text_elapsed = 0.0
        merge_elapsed = 0.0
        verify_elapsed = 0.0

        stage_start = time.perf_counter()
        quality = assess_document_quality(input_path, self.settings)
        quality_elapsed = time.perf_counter() - stage_start

        if self._should_try_pdf_text(input_path):
            try:
                stage_start = time.perf_counter()
                pdf_text = self.pdf_text_engine.parse(input_path, options.lang_hint.value)
                pdf_text_elapsed = time.perf_counter() - stage_start
                if is_pdf_text_result_usable(pdf_text, self.settings):
                    decision = ParseDecision(status="pass", reason="PDF text layer parsed without OCR.")
                    response = self._build_response(request_id, pdf_text, quality, options, decision)
                    logger.info(
                        "parse timings request_id=%s quality=%.3fs pdf_text=%.3fs total=%.3fs "
                        "pdf_text_score=%.3f quality_score=%.3f",
                        request_id,
                        quality_elapsed,
                        pdf_text_elapsed,
                        time.perf_counter() - total_start,
                        pdf_text.page_confidence,
                        quality.score,
                    )
                    return response
                logger.info("pdf text parser result too sparse; falling back to OCR")
            except Exception as exc:
                pdf_text_elapsed = time.perf_counter() - stage_start
                logger.info("pdf text parser skipped; falling back to OCR: %s", self._compact_error(str(exc)))

        stage_start = time.perf_counter()
        primary = self.primary_engine.parse(input_path, options.lang_hint.value)
        primary_elapsed = time.perf_counter() - stage_start
        primary_score = primary.page_confidence

        fallback: EngineParseResult | None = None
        fallback_error: str | None = None
        if options.enable_fallback and self._needs_fallback(primary_score, quality):
            try:
                stage_start = time.perf_counter()
                fallback = self.fallback_engine.parse(input_path, options.lang_hint.value)
                fallback_elapsed = time.perf_counter() - stage_start
            except Exception as exc:  # pragma: no cover - exercised via orchestrator tests
                fallback_elapsed = time.perf_counter() - stage_start
                fallback = None
                fallback_error = self._compact_error(str(exc))

        stage_start = time.perf_counter()
        merged = merge_results(primary, fallback, self.settings)
        merge_elapsed = time.perf_counter() - stage_start

        stage_start = time.perf_counter()
        merged = self._apply_qwen_verification_if_needed(input_path, merged)
        verify_elapsed = time.perf_counter() - stage_start

        decision = self._build_decision(merged.page_confidence, quality)
        if fallback_error:
            decision = decision.model_copy(
                update={
                    "reason": f"{decision.reason} Fallback skipped: {fallback_error}",
                }
            )
        response = self._build_response(request_id, merged, quality, options, decision)
        logger.info(
            "parse timings request_id=%s quality=%.3fs pdf_text=%.3fs primary=%.3fs fallback=%.3fs "
            "merge=%.3fs verify=%.3fs total=%.3fs primary_score=%.3f quality_score=%.3f",
            request_id,
            quality_elapsed,
            pdf_text_elapsed,
            primary_elapsed,
            fallback_elapsed,
            merge_elapsed,
            verify_elapsed,
            time.perf_counter() - total_start,
            primary_score,
            quality.score,
        )
        return response

    def _should_try_pdf_text(self, input_path: str) -> bool:
        return self.settings.pdf_text_parse_enabled and Path(input_path).suffix.lower() == ".pdf"

    def _build_response(
        self,
        request_id: str,
        result: EngineParseResult,
        quality: QualityAssessment,
        options: ParseOptions,
        decision: ParseDecision,
    ) -> ParseResponse:
        pages = self._attach_quality_to_pages(result.pages, quality)
        blocks = list(itertools.chain.from_iterable(page.blocks for page in pages))
        tables = list(itertools.chain.from_iterable(page.tables for page in pages))
        reading_order = list(itertools.chain.from_iterable(page.reading_order for page in pages))

        markdown = result.markdown if options.output_format in {OutputFormat.markdown, OutputFormat.both} else None
        if options.output_format == OutputFormat.json:
            markdown = None

        review_queued = decision.status == "fail"
        review_reason = decision.reason if review_queued else None

        return ParseResponse(
            request_id=request_id,
            decision=decision,
            pages=pages,
            blocks=blocks,
            tables=tables,
            reading_order=reading_order,
            quality_flags=quality.flags,
            markdown=markdown,
            review_queued=review_queued,
            review_reason=review_reason,
        )

    def _needs_fallback(self, primary_score: float, quality: QualityAssessment) -> bool:
        if primary_score < self.settings.confidence_pass_threshold:
            return True
        if quality.score < self.settings.quality_fail_threshold:
            return True
        return False

    def _build_decision(self, score: float, quality: QualityAssessment) -> ParseDecision:
        quality_ok = quality.score >= self.settings.quality_fail_threshold
        if score >= self.settings.confidence_pass_threshold and quality_ok:
            return ParseDecision(status="pass", reason="High confidence parse result.")
        if score >= self.settings.confidence_borderline_threshold and quality_ok:
            return ParseDecision(status="borderline", reason="Moderate confidence; fallback or review recommended.")
        # Low confidence OR failing document quality queues for manual review, so a
        # high-confidence parse on a poor-quality image is not silently passed.
        reasons: list[str] = []
        if score < self.settings.confidence_borderline_threshold:
            reasons.append("low confidence")
        if not quality_ok:
            reasons.append("low document quality")
        return ParseDecision(status="fail", reason="Queued for manual review: " + ", ".join(reasons) + ".")

    def _apply_qwen_verification_if_needed(self, input_path: str, result: EngineParseResult) -> EngineParseResult:
        if self.verifier is None:
            return result

        # The verifier attaches input_path as the page image, which is only correct
        # for a single-image input. For a (multi-page) PDF we cannot supply the right
        # per-page image without a PDF renderer, so skip rather than verify each page
        # against the wrong visual evidence.
        if Path(input_path).suffix.lower() == ".pdf":
            logger.info("qwen verification skipped: per-page image unavailable for PDF input")
            return result

        pages = []
        for page in result.pages:
            if page.confidence >= self.settings.confidence_borderline_threshold:
                pages.append(page)
                continue
            patch = self.verifier.verify_page(input_path, page)
            if not patch or "corrections" not in patch:
                pages.append(page)
                continue
            pages.append(self._patch_page(page, patch["corrections"]))

        return EngineParseResult(
            engine_name=result.engine_name,
            pages=pages,
            markdown=result.markdown,
            raw=result.raw,
        )

    @staticmethod
    def _patch_page(page: PageParseResult, corrections: object) -> PageParseResult:
        if not isinstance(corrections, list):
            return page
        blocks = page.blocks
        by_id = {b.block_id: b for b in blocks}
        changed = False
        for corr in corrections:
            if not isinstance(corr, dict):
                continue
            block_id = str(corr.get("block_id", "")).strip()
            content = str(corr.get("content", "")).strip()
            conf = corr.get("confidence")
            if not block_id or not content or block_id not in by_id:
                continue
            old = by_id[block_id]
            new_conf = old.confidence
            if isinstance(conf, (float, int)):
                new_conf = max(new_conf, float(conf))
            by_id[block_id] = old.model_copy(update={"content": content, "confidence": new_conf})
            changed = True
        # A no-op / non-matching verifier response must not touch the page. And a
        # real correction can only raise confidence: never overwrite the page score
        # with a raw block-average (zero-confidence blocks are legitimate, see the
        # normalizer's confidence heuristics) or borderline pages collapse to fail.
        if not changed:
            return page
        new_blocks = [by_id[b.block_id] for b in blocks]
        new_conf = page.confidence
        if new_blocks:
            block_avg = sum(b.confidence for b in new_blocks) / len(new_blocks)
            new_conf = max(page.confidence, block_avg)
        return page.model_copy(update={"blocks": new_blocks, "confidence": new_conf})

    @staticmethod
    def _attach_quality_to_pages(pages: list[PageParseResult], quality: QualityAssessment) -> list[PageParseResult]:
        return [page.model_copy(update={"quality_score": quality.score}) for page in pages]

    @staticmethod
    def _compact_error(message: str, max_len: int = 220) -> str:
        compact = " ".join((message or "").split())
        if len(compact) <= max_len:
            return compact
        return compact[: max_len - 3] + "..."
