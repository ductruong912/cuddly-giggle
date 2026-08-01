"""OCR → LLM extraction pipeline, run with bounded concurrency off the event loop.

Both extraction routes (local and online) drive the same three stages: parse the
document, send the Markdown to the LLM, then persist the artifacts. This service
owns that sequence so the routes only translate HTTP into a call.
"""
from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Protocol
import uuid

from config.config import Settings, settings
from config.pipeline_logging import pipeline_message, request_logging_context
from core.domain.schemas import (
    ExtractionValidation,
    LLMExtractionOCRMetadata,
    LLMExtractionResponse,
    ParseDecision,
    ParseResponse,
    ValidationIssue,
)
from services.concurrency import PipelineLimiters
from services.llm_extraction import LLMExtractionService
from services.output import save_extraction_artifacts, save_parse_artifacts
from services.persistence import ExtractionRecord, ExtractionStore
from services.validation import ExtractionOutcome, SelfHealingExtractor


logger = logging.getLogger(__name__)


class DocumentExtractionFailed(Exception):
    """The pipeline hit an error that is not attributable to a known dependency."""


class DocumentParser(Protocol):
    """The parse contract shared by the local and online orchestrators."""

    def parse(self, input_path: str, *, request_id: str | None = None) -> ParseResponse: ...


class DocumentExtractionService:
    """Run parse → extract → save for one document, one stage slot at a time."""

    def __init__(
        self,
        parser: DocumentParser,
        extractor: LLMExtractionService,
        limiters: PipelineLimiters,
        *,
        route_label: str,
        app_settings: Settings = settings,
        store: ExtractionStore | None = None,
    ) -> None:
        self.parser = parser
        self.extractor = extractor
        self.limiters = limiters
        self.route_label = route_label
        self.settings = app_settings
        self.store = store
        self.validator = SelfHealingExtractor(extractor, app_settings=app_settings)

    async def extract_document(self, source_path: Path, *, filename: str) -> LLMExtractionResponse:
        """Parse a staged document, extract structured data, and save both artifacts."""
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        total_start = time.perf_counter()
        try:
            ocr_start = time.perf_counter()
            parse_response = await self.limiters.ocr.run(
                self.parser.parse,
                str(source_path),
                request_id=request_id,
            )
            ocr_elapsed = time.perf_counter() - ocr_start

            llm_start = time.perf_counter()
            outcome = await self._extract(parse_response)
            llm_elapsed = time.perf_counter() - llm_start

            save_start = time.perf_counter()
            saved = await self.limiters.io.run(
                self._save_artifacts, parse_response, outcome.data, filename
            )
            save_elapsed = time.perf_counter() - save_start

            await self._persist(
                parse_response,
                outcome,
                filename,
                duration_ms=int((time.perf_counter() - total_start) * 1000),
            )
        except RuntimeError:
            # Engine, LLM-provider and admission failures already map to a precise
            # status code in the API layer; let them through untouched.
            raise
        except Exception as exc:
            logger.exception(
                pipeline_message("FAILED", "%s extraction request error", request_id=request_id),
                self.route_label,
            )
            raise DocumentExtractionFailed(f"Unexpected extraction error: {exc}") from exc

        logger.info(
            pipeline_message(
                "COMPLETED route=%s pages=%s markdown_chars=%s ocr=%.3fs llm=%.3fs "
                "save=%.3fs total=%.3fs validation=%s attempts=%s%s saved=%s",
                request_id=parse_response.request_id,
            ),
            self.route_label,
            len(parse_response.pages),
            len(parse_response.markdown or ""),
            ocr_elapsed,
            llm_elapsed,
            save_elapsed,
            time.perf_counter() - total_start,
            "valid" if outcome.is_valid else "needs_review",
            outcome.attempts,
            self._engine_summary(parse_response),
            ",".join(saved) or "none",
        )
        return self._build_response(parse_response, outcome)

    @staticmethod
    def _engine_summary(parse_response: ParseResponse) -> str:
        """Provider, runtime and billed cost for engines that report them (DataLab)."""
        metadata = parse_response.engine_metadata or {}
        if not metadata:
            return ""
        parts = [f"provider={metadata.get('provider') or parse_response.engine_name or 'local'}"]
        runtime = metadata.get("runtime")
        if runtime is not None:
            parts.append(f"engine_runtime={runtime}s")
        cost_breakdown = metadata.get("cost_breakdown")
        if isinstance(cost_breakdown, dict):
            parts.append(f"cost_cents={cost_breakdown.get('final_cost_cents', 'n/a')}")
        return " " + " ".join(parts)

    async def extract_markdown(
        self,
        markdown: str,
        *,
        reason: str,
        artifact_name: str | None = None,
    ) -> LLMExtractionResponse:
        """Extract structured data from Markdown that was supplied directly."""
        parse_response = ParseResponse(
            request_id=f"llm_{uuid.uuid4().hex[:12]}",
            decision=ParseDecision(reason=reason),
            pages=[],
            blocks=[],
            tables=[],
            reading_order=[],
            markdown=markdown,
        )
        outcome = await self._extract(parse_response)
        if artifact_name:
            await self.limiters.io.run(save_extraction_artifacts, outcome.data, artifact_name)
        return self._build_response(parse_response, outcome)

    async def _persist(
        self,
        parse_response: ParseResponse,
        outcome: ExtractionOutcome,
        filename: str,
        *,
        duration_ms: int,
    ) -> None:
        """Record the extraction in the database, when one is configured.

        With ``DATABASE_PERSISTENCE_REQUIRED`` on, a write failure fails the
        request: returning 200 for a result that was never recorded loses data
        silently, and the caller can retry a 503.
        """
        if self.store is None:
            return

        record = ExtractionRecord(
            request_id=parse_response.request_id,
            source_filename=filename,
            route=self.route_label,
            engine=parse_response.engine_name or None,
            page_count=len(parse_response.pages),
            validation_status="valid" if outcome.is_valid else "needs_review",
            attempts=outcome.attempts,
            healed=outcome.healed,
            data=outcome.data,
            issues=[violation.as_dict() for violation in outcome.violations],
            markdown=parse_response.markdown,
            duration_ms=duration_ms,
        )
        try:
            await self.limiters.io.run(self.store.save, record)
        except Exception:
            logger.exception(
                pipeline_message(
                    "FAILED", "could not persist the extraction",
                    request_id=parse_response.request_id,
                )
            )
            if self.settings.database_persistence_required:
                raise
            logger.warning(
                "continuing without a stored record; DATABASE_PERSISTENCE_REQUIRED is off"
            )

    async def _extract(self, parse_response: ParseResponse) -> ExtractionOutcome:
        """Extract and validate inside one LLM slot, so retries cost latency only."""
        return await self.limiters.llm.run(self._extract_blocking, parse_response)

    def _extract_blocking(self, parse_response: ParseResponse) -> ExtractionOutcome:
        with request_logging_context(parse_response.request_id):
            return self.validator.extract(parse_response)

    @staticmethod
    def _save_artifacts(
        parse_response: ParseResponse,
        data: dict[str, object],
        filename: str,
    ) -> list[str]:
        return save_parse_artifacts(parse_response, filename) + save_extraction_artifacts(
            data, filename
        )

    @staticmethod
    def _build_response(
        parse_response: ParseResponse,
        outcome: ExtractionOutcome,
    ) -> LLMExtractionResponse:
        return LLMExtractionResponse(
            request_id=parse_response.request_id,
            ocr=LLMExtractionOCRMetadata(
                decision=parse_response.decision.reason,
                page_count=len(parse_response.pages),
            ),
            data=outcome.data,
            validation=ExtractionValidation(
                status="valid" if outcome.is_valid else "needs_review",
                attempts=outcome.attempts,
                healed=outcome.healed,
                issues=[ValidationIssue(**violation.as_dict()) for violation in outcome.violations],
            ),
        )
