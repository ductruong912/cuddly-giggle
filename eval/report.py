"""Aggregate case outcomes into the numbers the run is meant to produce.

Three of these matter most: field-level accuracy, the share of documents that
need a human, and the self-healing recovery rate — the fraction of extractions
that failed validation on the first attempt and were correct by the last.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import logging
from typing import Any

from eval.runner import CaseOutcome


logger = logging.getLogger(__name__)

SEPARATOR = "=" * 72
CASE_ID_WIDTH = 28


@dataclass(frozen=True)
class RunContext:
    """The settings a run's numbers depend on, recorded so they stay interpretable."""

    source_name: str
    retry_budget: int
    tolerance_ratio: float


class EvalReport:
    """Summarize a set of case outcomes as text and as JSON."""

    def __init__(self, outcomes: list[CaseOutcome], context: RunContext) -> None:
        self.outcomes = outcomes
        self.context = context

    # -- aggregate figures ------------------------------------------------------

    @property
    def case_count(self) -> int:
        return len(self.outcomes)

    @property
    def total_fields(self) -> int:
        return sum(outcome.score.total_fields for outcome in self.outcomes)

    @property
    def correct_fields(self) -> int:
        return sum(outcome.score.correct_fields for outcome in self.outcomes)

    @property
    def field_accuracy(self) -> float:
        """Share of ground-truth fields reproduced exactly, pooled over all cases."""
        return self.correct_fields / self.total_fields if self.total_fields else 0.0

    @property
    def exact_matches(self) -> list[CaseOutcome]:
        return [outcome for outcome in self.outcomes if outcome.score.is_exact]

    @property
    def needs_review(self) -> list[CaseOutcome]:
        return [outcome for outcome in self.outcomes if not outcome.is_valid]

    @property
    def initially_invalid(self) -> list[CaseOutcome]:
        return [outcome for outcome in self.outcomes if outcome.initially_invalid]

    @property
    def recovered(self) -> list[CaseOutcome]:
        return [outcome for outcome in self.outcomes if outcome.healed]

    @property
    def recovery_rate(self) -> float:
        """Share of first-attempt failures that a targeted retry put right."""
        initially_invalid = len(self.initially_invalid)
        return len(self.recovered) / initially_invalid if initially_invalid else 0.0

    @property
    def silent_failures(self) -> list[CaseOutcome]:
        """Cases that satisfied every check but still do not match ground truth."""
        return [outcome for outcome in self.outcomes if outcome.is_silent_failure]

    @property
    def errored(self) -> list[CaseOutcome]:
        return [outcome for outcome in self.outcomes if outcome.error]

    @property
    def mean_attempts(self) -> float:
        if not self.outcomes:
            return 0.0
        return sum(outcome.attempts for outcome in self.outcomes) / len(self.outcomes)

    @property
    def total_seconds(self) -> float:
        return sum(outcome.duration_seconds for outcome in self.outcomes)

    def accuracy_by_field(self) -> list[tuple[str, int, int]]:
        """Per-field-name (correct, total) counts, worst first."""
        totals: Counter[str] = Counter()
        correct: Counter[str] = Counter()
        for outcome in self.outcomes:
            for result in outcome.score.fields:
                name = result.field.rsplit(".", 1)[-1]
                totals[name] += 1
                correct[name] += int(result.correct)
        return sorted(
            ((name, correct[name], total) for name, total in totals.items()),
            key=lambda row: (row[1] / row[2] if row[2] else 0.0, row[0]),
        )

    # -- rendering --------------------------------------------------------------

    def as_dict(self) -> dict[str, Any]:
        """The whole report as plain data, for storing or diffing between runs."""
        return {
            "source": self.context.source_name,
            "settings": {
                "self_heal_retry_budget": self.context.retry_budget,
                "line_total_tolerance_ratio": self.context.tolerance_ratio,
            },
            "totals": {
                "cases": self.case_count,
                "field_accuracy": round(self.field_accuracy, 4),
                "fields_correct": self.correct_fields,
                "fields_total": self.total_fields,
                "exact_matches": len(self.exact_matches),
                "needs_review": len(self.needs_review),
                "errors": len(self.errored),
                "mean_attempts": round(self.mean_attempts, 3),
                "total_seconds": round(self.total_seconds, 3),
            },
            "self_healing": {
                "initially_invalid": len(self.initially_invalid),
                "recovered": len(self.recovered),
                "recovery_rate": round(self.recovery_rate, 4),
                "unrecovered": len(self.initially_invalid) - len(self.recovered),
            },
            "silent_failures": [
                {
                    "case_id": outcome.case_id,
                    "description": outcome.description,
                    "wrong_fields": [result.field for result in outcome.score.wrong_fields],
                    "missed_items": outcome.score.missed_items,
                    "spurious_items": outcome.score.spurious_items,
                }
                for outcome in self.silent_failures
            ],
            "accuracy_by_field": [
                {"field": name, "correct": correct, "total": total}
                for name, correct, total in self.accuracy_by_field()
            ],
            "cases": [self._case_as_dict(outcome) for outcome in self.outcomes],
        }

    @staticmethod
    def _case_as_dict(outcome: CaseOutcome) -> dict[str, Any]:
        return {
            "case_id": outcome.case_id,
            "description": outcome.description,
            "accuracy": round(outcome.score.accuracy, 4),
            "fields_correct": outcome.score.correct_fields,
            "fields_total": outcome.score.total_fields,
            "exact": outcome.score.is_exact,
            "attempts": outcome.attempts,
            "status": "error" if outcome.error else ("valid" if outcome.is_valid else "needs_review"),
            "healed": outcome.healed,
            "silent_failure": outcome.is_silent_failure,
            "missed_items": outcome.score.missed_items,
            "spurious_items": outcome.score.spurious_items,
            "wrong_fields": [result.field for result in outcome.score.wrong_fields],
            "violations": [violation.as_dict() for violation in outcome.violations],
            "error": outcome.error,
            "duration_seconds": round(outcome.duration_seconds, 3),
        }

    def render(self) -> str:
        """Format the report for a terminal."""
        sections = [
            self._render_header(),
            self._render_totals(),
            self._render_self_healing(),
            self._render_silent_failures(),
            self._render_by_field(),
            self._render_cases(),
        ]
        return "\n".join(section for section in sections if section)

    def _render_header(self) -> str:
        return (
            f"{SEPARATOR}\n"
            f"Extraction evaluation - {self.context.source_name} source\n"
            f"{self.case_count} case(s) | self-heal retries={self.context.retry_budget} "
            f"| line-total tolerance={self.context.tolerance_ratio:.2%}\n"
            f"{SEPARATOR}"
        )

    def _render_totals(self) -> str:
        lines = [
            "",
            "Accuracy",
            f"  Field accuracy       {self.field_accuracy:6.1%}  "
            f"({self.correct_fields}/{self.total_fields} fields)",
            f"  Exact record match   {self._share(len(self.exact_matches)):6.1%}  "
            f"({len(self.exact_matches)}/{self.case_count} cases)",
            f"  Requiring review     {self._share(len(self.needs_review)):6.1%}  "
            f"({len(self.needs_review)}/{self.case_count} cases)",
        ]
        if self.errored:
            lines.append(f"  Errored              {len(self.errored)} case(s) never produced an extraction")
        return "\n".join(lines)

    def _render_self_healing(self) -> str:
        unrecovered = len(self.initially_invalid) - len(self.recovered)
        return "\n".join(
            [
                "",
                "Self-healing",
                f"  Invalid on attempt 1 {len(self.initially_invalid):>6}",
                f"  Recovered by retry   {len(self.recovered):>6}",
                f"  Still invalid        {unrecovered:>6}",
                f"  Recovery rate        {self.recovery_rate:6.1%}",
                f"  Mean attempts        {self.mean_attempts:>6.2f}",
            ]
        )

    def _render_silent_failures(self) -> str:
        """The blind spot: right by every check, still wrong against ground truth."""
        if not self.silent_failures:
            return "\nValidation blind spots\n  none - every valid record matched ground truth"
        lines = [
            "",
            f"Validation blind spots ({len(self.silent_failures)} case(s) passed every check but are wrong)",
        ]
        for outcome in self.silent_failures:
            detail = ", ".join(result.field for result in outcome.score.wrong_fields[:4]) or "-"
            if outcome.score.missed_items:
                detail = f"dropped {', '.join(outcome.score.missed_items)}"
            lines.append(f"  {outcome.case_id:<{CASE_ID_WIDTH}} {detail}")
        return "\n".join(lines)

    def _render_by_field(self) -> str:
        rows = self.accuracy_by_field()
        if not rows:
            return ""
        lines = ["", "Accuracy by field"]
        lines.extend(
            f"  {name:<20} {correct / total if total else 0.0:6.1%}  ({correct}/{total})"
            for name, correct, total in rows
        )
        return "\n".join(lines)

    def _render_cases(self) -> str:
        lines = [
            "",
            f"  {'case':<{CASE_ID_WIDTH}} {'acc':>6} {'att':>4}  {'status':<12} notes",
            f"  {'-' * CASE_ID_WIDTH} {'-' * 6} {'-' * 4}  {'-' * 12} {'-' * 20}",
        ]
        for outcome in self.outcomes:
            status = "error" if outcome.error else ("valid" if outcome.is_valid else "needs_review")
            notes = []
            if outcome.healed:
                notes.append(f"healed on attempt {outcome.attempts}")
            if outcome.is_silent_failure:
                notes.append("SILENT FAILURE")
            if outcome.error:
                notes.append(outcome.error)
            lines.append(
                f"  {outcome.case_id:<{CASE_ID_WIDTH}} {outcome.score.accuracy:6.1%} "
                f"{outcome.attempts:>4}  {status:<12} {'; '.join(notes)}".rstrip()
            )
        lines.append("")
        lines.append(f"Completed in {self.total_seconds:.2f}s")
        return "\n".join(lines)

    def _share(self, count: int) -> float:
        return count / self.case_count if self.case_count else 0.0
