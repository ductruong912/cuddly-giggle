"""Metric aggregation, including the blind-spot count the harness exists to expose."""
from __future__ import annotations

import json

import pytest

from eval.report import EvalReport, RunContext
from eval.runner import CaseOutcome
from eval.scoring import CaseScore, FieldResult


@pytest.fixture
def context() -> RunContext:
    return RunContext(source_name="replay", retry_budget=2, tolerance_ratio=0.01)


def make_outcome(
    case_id: str,
    *,
    correct: int,
    total: int,
    attempts: int,
    is_valid: bool,
    healed: bool = False,
    exact: bool = True,
    error: str | None = None,
) -> CaseOutcome:
    fields = [FieldResult(f"f{index}", 1, 1, index < correct) for index in range(total)]
    score = CaseScore(
        case_id=case_id,
        fields=fields,
        missed_items=[] if exact else ["X"],
        spurious_items=[],
    )
    return CaseOutcome(
        case_id=case_id,
        description="",
        score=score,
        attempts=attempts,
        is_valid=is_valid,
        healed=healed,
        violations=[],
        duration_seconds=0.0,
        error=error,
    )


@pytest.fixture
def mixed_run() -> list[CaseOutcome]:
    return [
        make_outcome("clean", correct=4, total=4, attempts=1, is_valid=True),
        make_outcome("healed", correct=4, total=4, attempts=2, is_valid=True, healed=True),
        make_outcome("failed", correct=2, total=4, attempts=3, is_valid=False, exact=False),
        make_outcome("silent", correct=3, total=4, attempts=1, is_valid=True, exact=False),
    ]


def test_an_empty_run_does_not_divide_by_zero(context: RunContext) -> None:
    report = EvalReport([], context)

    assert report.field_accuracy == 0.0
    assert report.recovery_rate == 0.0
    assert report.mean_attempts == 0.0
    assert "0 case(s)" in report.render()


def test_field_accuracy_pools_across_cases(mixed_run: list, context: RunContext) -> None:
    report = EvalReport(mixed_run, context)

    assert (report.correct_fields, report.total_fields) == (13, 16)
    assert report.field_accuracy == pytest.approx(13 / 16)


def test_initially_invalid_covers_retried_and_failed(mixed_run: list, context: RunContext) -> None:
    report = EvalReport(mixed_run, context)

    assert {o.case_id for o in report.initially_invalid} == {"healed", "failed"}


def test_the_recovery_rate_is_recovered_over_initially_invalid(
    mixed_run: list, context: RunContext
) -> None:
    """The number the plan's Definition of Done asks to be reported."""
    assert EvalReport(mixed_run, context).recovery_rate == 0.5


def test_the_recovery_rate_is_zero_when_nothing_failed(context: RunContext) -> None:
    clean = [make_outcome(f"c{i}", correct=4, total=4, attempts=1, is_valid=True) for i in range(3)]

    report = EvalReport(clean, context)

    assert report.recovery_rate == 0.0
    assert report.field_accuracy == 1.0
    assert report.silent_failures == []


def test_needs_review_counts_only_invalid_cases(mixed_run: list, context: RunContext) -> None:
    assert [o.case_id for o in EvalReport(mixed_run, context).needs_review] == ["failed"]


def test_a_valid_but_inexact_case_is_a_blind_spot(mixed_run: list, context: RunContext) -> None:
    """Passed every check and still wrong: only ground truth can see these."""
    report = EvalReport(mixed_run, context)

    assert [o.case_id for o in report.silent_failures] == ["silent"]


def test_a_reviewed_case_is_not_a_blind_spot(mixed_run: list, context: RunContext) -> None:
    """A case already flagged for review is caught, not silently wrong."""
    assert "failed" not in {o.case_id for o in EvalReport(mixed_run, context).silent_failures}


def test_mean_attempts_averages_over_every_case(mixed_run: list, context: RunContext) -> None:
    assert EvalReport(mixed_run, context).mean_attempts == 1.75


def test_accuracy_by_field_is_worst_first(context: RunContext) -> None:
    score = CaseScore(
        case_id="c",
        fields=[
            FieldResult("po_number", 1, 1, True),
            FieldResult("items[A].quantity", 1, 2, False),
        ],
        missed_items=[],
        spurious_items=[],
    )
    outcome = CaseOutcome(
        case_id="c", description="", score=score, attempts=1, is_valid=True,
        healed=False, violations=[], duration_seconds=0.0,
    )

    rows = EvalReport([outcome], context).accuracy_by_field()

    assert [name for name, _, _ in rows] == ["quantity", "po_number"]


def test_the_json_report_is_serialisable(mixed_run: list, context: RunContext) -> None:
    payload = EvalReport(mixed_run, context).as_dict()

    assert json.loads(json.dumps(payload))["self_healing"]["recovery_rate"] == 0.5
    assert payload["totals"]["needs_review"] == 1
    assert len(payload["silent_failures"]) == 1


def test_the_report_records_the_settings_it_ran_with(
    mixed_run: list, context: RunContext
) -> None:
    """Accuracy is meaningless without the tolerance and retry budget behind it."""
    settings_used = EvalReport(mixed_run, context).as_dict()["settings"]

    assert settings_used == {"self_heal_retry_budget": 2, "line_total_tolerance_ratio": 0.01}


def test_an_errored_case_is_shown_as_an_error(context: RunContext) -> None:
    errored = make_outcome(
        "boom", correct=0, total=4, attempts=0, is_valid=False, exact=False,
        error="OSError: unreadable",
    )

    rendered = EvalReport([errored], context).render()

    assert "error" in rendered and "OSError" in rendered
