from __future__ import annotations

import itertools
import uuid

from app.core.config import Settings, settings
from app.domain.schemas import Block, OutputFormat, PageParseResult, ParseDecision, ParseOptions, ParseResponse, Table
from app.services.engines.base import EngineParseResult, ParseEngine
from app.services.engines.paddleocr_vl import PaddleOCRVLEngine
from app.services.engines.pp_structure_v3 import PPStructureV3Engine
from app.services.merge import merge_results
from app.services.quality import QualityAssessment, assess_document_quality
from app.services.qwen_verifier import QwenVerifier
from app.services.vietnamese_postprocess import postprocess_blocks, postprocess_markdown, postprocess_tables


class ParseOrchestrator:
    def __init__(
        self,
        app_settings: Settings = settings,
        primary_engine: ParseEngine | None = None,
        fallback_engine: ParseEngine | None = None,
    ) -> None:
        self.settings = app_settings
        self.primary_engine = primary_engine or PaddleOCRVLEngine(app_settings=self.settings)
        self.fallback_engine = fallback_engine or PPStructureV3Engine()
        self.verifier = None
        if self.settings.qwen_verifier_enabled:
            self.verifier = QwenVerifier(
                base_url=self.settings.qwen_verifier_base_url,
                model=self.settings.qwen_verifier_model,
                api_key=self.settings.qwen_verifier_api_key,
            )

    def parse(self, input_path: str, options: ParseOptions) -> ParseResponse:
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        quality = assess_document_quality(input_path)

        primary = self.primary_engine.parse(input_path, options.lang_hint.value)
        primary_score = primary.page_confidence

        fallback: EngineParseResult | None = None
        fallback_error: str | None = None
        if options.enable_fallback and self._needs_fallback(primary_score, quality):
            try:
                fallback = self.fallback_engine.parse(input_path, options.lang_hint.value)
            except Exception as exc:  # pragma: no cover - exercised via orchestrator tests
                fallback = None
                fallback_error = self._compact_error(str(exc))

        merged = merge_results(primary, fallback)
        merged = self._apply_qwen_verification_if_needed(input_path, merged)
        merged = self._apply_postprocess(merged)

        decision = self._build_decision(merged.page_confidence, quality)
        if fallback_error:
            decision = decision.model_copy(
                update={
                    "reason": f"{decision.reason} Fallback skipped: {fallback_error}",
                }
            )
        pages = self._attach_quality_to_pages(merged.pages, quality)
        blocks = list(itertools.chain.from_iterable(page.blocks for page in pages))
        tables = list(itertools.chain.from_iterable(page.tables for page in pages))
        reading_order = list(itertools.chain.from_iterable(page.reading_order for page in pages))

        markdown = merged.markdown if options.output_format in {OutputFormat.markdown, OutputFormat.both} else None
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
        if score >= self.settings.confidence_pass_threshold and quality.score >= self.settings.quality_fail_threshold:
            return ParseDecision(status="pass", reason="High confidence parse result.")
        if score >= self.settings.confidence_borderline_threshold:
            return ParseDecision(status="borderline", reason="Moderate confidence; fallback or review recommended.")
        return ParseDecision(status="fail", reason="Low confidence parse; queued for manual review.")

    def _apply_postprocess(self, result: EngineParseResult) -> EngineParseResult:
        pages: list[PageParseResult] = []
        for page in result.pages:
            processed_blocks = postprocess_blocks(page.blocks)
            processed_tables = postprocess_tables(page.tables)
            updated_conf = page.confidence
            if processed_blocks:
                scored = [b.confidence for b in processed_blocks if b.confidence > 0.0]
                if scored:
                    updated_conf = sum(scored) / len(scored)
            pages.append(
                page.model_copy(
                    update={
                        "blocks": processed_blocks,
                        "tables": processed_tables,
                        "confidence": updated_conf,
                    }
                )
            )
        return EngineParseResult(
            engine_name=result.engine_name,
            pages=pages,
            markdown=postprocess_markdown(result.markdown),
            raw=result.raw,
        )

    def _apply_qwen_verification_if_needed(self, input_path: str, result: EngineParseResult) -> EngineParseResult:
        if self.verifier is None:
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
        new_blocks = [by_id[b.block_id] for b in blocks]
        new_conf = page.confidence
        if new_blocks:
            new_conf = sum(b.confidence for b in new_blocks) / len(new_blocks)
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
