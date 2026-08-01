"""Run every case through a source and collect what happened.

One unreadable document must not abort a run, so a failing case is recorded as a
zero-scoring outcome and the run continues.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import time

from eval.labeled_set import EvalCase
from eval.scoring import CaseScore, RecordScorer
from eval.sources import ExtractionSource
from services.validation import RuleViolation


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CaseOutcome:
    """What one case produced: how accurate it was, and what validation made of it."""

    case_id: str
    description: str
    score: CaseScore
    attempts: int
    is_valid: bool
    healed: bool
    violations: list[RuleViolation]
    duration_seconds: float
    error: str | None = None

    @property
    def initially_invalid(self) -> bool:
        """True when the first attempt did not pass validation."""
        return not (self.attempts == 1 and self.is_valid)

    @property
    def is_silent_failure(self) -> bool:
        """True when validation was satisfied but the record is not the right one.

        These are the cases deterministic validation cannot catch on its own:
        a dropped line item, or figures that are self-consistent but misread.
        """
        return self.is_valid and not self.score.is_exact


class EvalRunner:
    """Score a labeled set against one extraction source."""

    def __init__(self, source: ExtractionSource, scorer: RecordScorer | None = None) -> None:
        self.source = source
        self.scorer = scorer or RecordScorer()

    def run(self, cases: list[EvalCase]) -> list[CaseOutcome]:
        """Run every case, in order, and return one outcome each."""
        logger.info("running %s case(s) through the %s source", len(cases), self.source.name)
        return [self._run_case(case) for case in cases]

    def _run_case(self, case: EvalCase) -> CaseOutcome:
        started = time.perf_counter()
        try:
            outcome = self.source.run(case)
        except Exception as exc:
            logger.exception("case %s could not be run", case.case_id)
            return self._failed_outcome(case, exc, time.perf_counter() - started)

        return CaseOutcome(
            case_id=case.case_id,
            description=case.description,
            score=self.scorer.score(case.case_id, case.expected, outcome.data),
            attempts=outcome.attempts,
            is_valid=outcome.is_valid,
            healed=outcome.healed,
            violations=list(outcome.violations),
            duration_seconds=time.perf_counter() - started,
        )

    def _failed_outcome(
        self, case: EvalCase, exc: Exception, duration: float
    ) -> CaseOutcome:
        """Record a case that never produced an extraction as a total miss."""
        return CaseOutcome(
            case_id=case.case_id,
            description=case.description,
            score=self.scorer.score(case.case_id, case.expected, {}),
            attempts=0,
            is_valid=False,
            healed=False,
            violations=[],
            duration_seconds=duration,
            error=f"{type(exc).__name__}: {exc}",
        )
