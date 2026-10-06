"""Where an extraction comes from: replayed answers, or the live pipeline.

Both sources end at the same place — ``SelfHealingExtractor`` — so the validation
and retry behaviour under test is the code that runs in production, not a
re-implementation of it.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

from config.config import Settings, settings
from core.domain.schemas import ParseDecision, ParseResponse
from eval.labeled_set import EvalCase
from services.validation import ExtractionOutcome, SelfHealingExtractor


logger = logging.getLogger(__name__)

REPLAY_MARKDOWN = "# Replayed case\n\nNo document was read; answers are scripted."


class DocumentParser(Protocol):
    """The parse contract implemented by the local orchestrator."""

    def parse(self, input_path: str, *, request_id: str | None = None) -> ParseResponse: ...


class StructuredExtractor(Protocol):
    """The extraction call the self-heal loop drives."""

    def extract(
        self, parse_response: ParseResponse, *, correction: str | None = None
    ) -> dict[str, Any]: ...


class ExtractionSource(Protocol):
    """Produces one validated extraction outcome for a case."""

    name: str

    def run(self, case: EvalCase) -> ExtractionOutcome: ...


class ScriptedExtractor:
    """Hands back one recorded answer per call, repeating the last one forever.

    Repeating matters: a case that lists a single wrong answer models a document
    the extraction keeps misreading, which is what drives a case to
    ``needs_review`` rather than to a recovery.
    """

    def __init__(self, answers: list[dict[str, Any]]) -> None:
        self._answers = list(answers)
        self.corrections: list[str | None] = []

    def extract(
        self, parse_response: ParseResponse, *, correction: str | None = None
    ) -> dict[str, Any]:
        """Return the next scripted answer, recording the correction it was given."""
        del parse_response
        self.corrections.append(correction)
        index = min(len(self.corrections) - 1, len(self._answers) - 1)
        return self._answers[index]


class ReplayExtractionSource:
    """Drive the validation loop with recorded answers instead of a live model."""

    name = "replay"

    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings

    def run(self, case: EvalCase) -> ExtractionOutcome:
        """Replay the case's answers through the real self-healing extractor."""
        if not case.attempts:
            raise ValueError(f"case {case.case_id!r} has no recorded attempts to replay")
        extractor = ScriptedExtractor(case.attempts)
        healer = SelfHealingExtractor(extractor, app_settings=self.settings)
        return healer.extract(self._stub_parse_response(case))

    @staticmethod
    def _stub_parse_response(case: EvalCase) -> ParseResponse:
        return ParseResponse(
            request_id=f"eval_{case.case_id}",
            decision=ParseDecision(reason="replayed labeled-set case"),
            pages=[],
            blocks=[],
            tables=[],
            reading_order=[],
            markdown=REPLAY_MARKDOWN,
        )


class LiveExtractionSource:
    """Run the real OCR and extraction pipeline against the case's document."""

    def __init__(
        self,
        parser: DocumentParser,
        extractor: StructuredExtractor,
        *,
        app_settings: Settings = settings,
    ) -> None:
        self.parser = parser
        self.extractor = extractor
        self.settings = app_settings
        self.name = "live-local"

    def run(self, case: EvalCase) -> ExtractionOutcome:
        """Parse the document, then extract and validate it exactly as the API does."""
        if case.document is None:
            raise ValueError(f"case {case.case_id!r} has no document to parse")
        if not case.document.is_file():
            raise FileNotFoundError(f"case {case.case_id!r} points at a missing file: {case.document}")

        logger.info("parsing %s for case %s", case.document.name, case.case_id)
        parse_response = self.parser.parse(
            str(case.document), request_id=f"eval_{case.case_id}"
        )
        healer = SelfHealingExtractor(self.extractor, app_settings=self.settings)
        return healer.extract(parse_response)
