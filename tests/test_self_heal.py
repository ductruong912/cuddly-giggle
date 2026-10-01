"""The retry loop: what it re-asks, when it stops, and what it reports."""
from __future__ import annotations

from typing import Any

import pytest

from core.domain.schemas import ParseResponse
from services.validation import SelfHealingExtractor, Severity, build_correction_prompt


class ScriptedExtractor:
    """Returns one queued answer per call, repeating the last one indefinitely."""

    def __init__(self, answers: list[dict[str, Any]]) -> None:
        self.answers = list(answers)
        self.corrections: list[str | None] = []

    def extract(
        self, parse_response: ParseResponse, *, correction: str | None = None
    ) -> dict[str, Any]:
        del parse_response
        self.corrections.append(correction)
        return self.answers[min(len(self.corrections) - 1, len(self.answers) - 1)]


@pytest.fixture
def shifted_order(valid_order: dict) -> dict:
    """A line whose stated total is a tenth of what its parts multiply to."""
    shifted = {**valid_order, "items": [dict(valid_order["items"][0])]}
    shifted["items"][0]["extension"] = 500000
    return shifted


def test_a_valid_answer_costs_one_call(valid_order: dict, parse_response: ParseResponse) -> None:
    extractor = ScriptedExtractor([valid_order])

    outcome = SelfHealingExtractor(extractor).extract(parse_response)

    assert outcome.attempts == 1
    assert outcome.is_valid
    assert outcome.healed is False
    assert extractor.corrections == [None], "a first attempt must carry no correction"


def test_a_failed_answer_is_retried_and_recovers(
    valid_order: dict, shifted_order: dict, parse_response: ParseResponse
) -> None:
    extractor = ScriptedExtractor([shifted_order, valid_order])

    outcome = SelfHealingExtractor(extractor).extract(parse_response)

    assert outcome.attempts == 2
    assert outcome.is_valid
    assert outcome.healed is True
    assert outcome.data == valid_order
    correction = extractor.corrections[1] or ""
    assert "items.0" in correction
    assert "5000000.00" in correction and "500000.00" in correction
    assert "column was read" in correction


def test_retries_stop_at_the_configured_budget(
    shifted_order: dict, parse_response: ParseResponse
) -> None:
    extractor = ScriptedExtractor([shifted_order])

    outcome = SelfHealingExtractor(extractor).extract(parse_response)

    assert outcome.attempts == 3, "1 initial attempt + LLM_SELF_HEAL_MAX_RETRIES"
    assert not outcome.is_valid
    assert outcome.healed is False
    assert outcome.data == shifted_order
    assert outcome.blocking_violations
    assert outcome.record is None


def test_a_business_rule_error_also_triggers_a_retry(
    valid_order: dict, parse_response: ParseResponse
) -> None:
    bad_date = {**valid_order, "po_date": "2026/06/05"}
    extractor = ScriptedExtractor([bad_date, valid_order])

    outcome = SelfHealingExtractor(extractor).extract(parse_response)

    assert outcome.attempts == 2
    assert outcome.is_valid
    assert "po_date" in (extractor.corrections[1] or "")


def test_warnings_do_not_consume_a_retry(
    valid_order: dict, parse_response: ParseResponse
) -> None:
    """A duplicate code can be genuine, so it is reported rather than re-asked."""
    valid_order["items"].append({**valid_order["items"][0], "customer_number": "CT-9002"})
    extractor = ScriptedExtractor([valid_order])

    outcome = SelfHealingExtractor(extractor).extract(parse_response)

    assert outcome.attempts == 1
    assert outcome.is_valid
    assert [v.severity for v in outcome.violations] == [Severity.warning]


def test_the_correction_prompt_quotes_the_previous_answer(valid_order: dict) -> None:
    from services.validation import RuleViolation

    violation = RuleViolation(field="po_date", message="wrong format", severity=Severity.error)

    prompt = build_correction_prompt(valid_order, [violation])

    assert "215497" in prompt, "the prior answer must be quoted back"
    assert "1. field `po_date`: wrong format" in prompt
