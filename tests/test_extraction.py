"""Purchase-order schema, business rules and bounded correction retries."""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, ConfigDict, ValidationError

from config.config import settings
from core.domain.purchase_order import PurchaseOrder
from core.domain.schemas import ParseResponse
from core.domain.strict_schema import (
    UNSUPPORTED_KEYWORDS,
    assert_strict_schema,
    to_strict_json_schema,
)
from core.prompts.prompt import EXTRACTION_JSON_SCHEMA
from services.validation import (
    BusinessRuleChecker,
    Severity,
    SelfHealingExtractor,
    build_correction_prompt,
)


def test_a_reconciling_order_validates(valid_order: dict) -> None:
    order = PurchaseOrder.model_validate(valid_order)
    assert order.po_number == "215497"
    assert order.items[0].extension == 5000000


def test_a_column_shift_is_rejected(valid_order: dict) -> None:
    """quantity x unit_price = 5,000,000, but the document is read as 500,000."""
    valid_order["items"][0]["extension"] = 500000

    with pytest.raises(ValidationError) as caught:
        PurchaseOrder.model_validate(valid_order)

    message = str(caught.value)
    assert "line total mismatch" in message
    # Both figures must appear, or the retry cannot be targeted.
    assert "5000000.00" in message and "500000.00" in message


def test_display_rounding_is_tolerated(valid_order: dict) -> None:
    """A unit price printed to two decimals leaves the product slightly short."""
    valid_order["items"][0].update(quantity=7, unit_price=142857.14, extension=1000000)

    order = PurchaseOrder.model_validate(valid_order)

    assert order.items[0].quantity == 7


def test_a_drift_beyond_the_tolerance_is_rejected(valid_order: dict) -> None:
    tolerated = 5000000 * settings.po_line_total_tolerance_ratio
    valid_order["items"][0]["extension"] = 5000000 + tolerated * 2

    with pytest.raises(ValidationError, match="line total mismatch"):
        PurchaseOrder.model_validate(valid_order)


def test_a_null_extension_skips_the_arithmetic(valid_order: dict) -> None:
    """Documents that print no line total get structural validation only."""
    valid_order["items"][0]["extension"] = None

    order = PurchaseOrder.model_validate(valid_order)

    assert order.items[0].extension is None


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("toto_number", "   ", "toto_number is empty"),
        ("quantity", 0, "quantity must be greater than zero"),
        ("quantity", -1, "quantity must be greater than zero"),
        ("unit_price", -5, "unit_price cannot be negative"),
    ],
)
def test_implausible_line_values_are_rejected(
    valid_order: dict, field: str, value: object, expected: str
) -> None:
    valid_order["items"][0][field] = value
    # Keep the arithmetic consistent so the line fails on the field under test.
    valid_order["items"][0]["extension"] = None

    with pytest.raises(ValidationError, match=expected):
        PurchaseOrder.model_validate(valid_order)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("po_number", "  ", "po_number is empty"),
        ("po_date", "", "po_date is empty"),
        ("items", [], "no line items were extracted"),
    ],
)
def test_an_incomplete_header_is_rejected(
    valid_order: dict, field: str, value: object, expected: str
) -> None:
    valid_order[field] = value

    with pytest.raises(ValidationError, match=expected):
        PurchaseOrder.model_validate(valid_order)


def test_unexpected_fields_are_rejected(valid_order: dict) -> None:
    """`extra="forbid"` keeps the model and its JSON Schema in step."""
    valid_order["invented_field"] = "x"

    with pytest.raises(ValidationError):
        PurchaseOrder.model_validate(valid_order)


def test_the_shipped_schema_is_strict_mode_valid() -> None:
    """A malformed schema must be a startup error, not a per-request 400."""
    assert_strict_schema(EXTRACTION_JSON_SCHEMA)
    assert EXTRACTION_JSON_SCHEMA == to_strict_json_schema(PurchaseOrder)

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
            properties = node.get("properties")
            if isinstance(properties, dict):
                assert set(node.get("required", [])) == set(properties)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(EXTRACTION_JSON_SCHEMA)


def test_the_line_item_fields_survive_generation() -> None:
    item_schema = EXTRACTION_JSON_SCHEMA["$defs"]["PurchaseOrderItem"]

    assert set(item_schema["properties"]) == {
        "toto_number",
        "customer_number",
        "quantity",
        "unit_price",
        "extension",
    }
    assert item_schema["properties"]["extension"]["description"]
    assert EXTRACTION_JSON_SCHEMA["properties"]["po_date"]["description"]


@pytest.mark.parametrize("keyword", sorted(UNSUPPORTED_KEYWORDS))
def test_unsupported_keywords_are_caught(keyword: str) -> None:
    with pytest.raises(ValueError, match=keyword):
        assert_strict_schema(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"a": {"type": "string"}},
                "required": ["a"],
                keyword: {},
            }
        )


def test_a_missing_required_key_is_caught() -> None:
    with pytest.raises(ValueError, match="required"):
        assert_strict_schema(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
                "required": ["a"],
            }
        )


def test_open_objects_are_caught() -> None:
    with pytest.raises(ValueError, match="additionalProperties"):
        assert_strict_schema(
            {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        )


def test_generation_hardens_a_permissive_model() -> None:
    """Defaults make a field optional, which strict mode does not allow."""

    class Permissive(BaseModel):
        model_config = ConfigDict(extra="allow")

        name: str = "unnamed"

    schema = to_strict_json_schema(Permissive)

    assert schema["additionalProperties"] is False
    assert schema["required"] == ["name"]
    assert "default" not in schema["properties"]["name"]


TODAY = date(2026, 8, 1)


@pytest.fixture
def checker() -> BusinessRuleChecker:
    """A checker with time frozen, so the plausibility window never drifts."""
    return BusinessRuleChecker(today=TODAY)


@pytest.mark.parametrize("po_date", ["05-06-2026", "01-07-2027"])
def test_dates_inside_the_window_pass(checker: BusinessRuleChecker, valid_order: dict, po_date: str) -> None:
    valid_order["po_date"] = po_date
    assert checker.check(PurchaseOrder.model_validate(valid_order)) == []


@pytest.mark.parametrize(
    ("po_date", "severity", "message"),
    [
        ("2026/06/05", Severity.error, "DD-MM-YYYY"),
        ("05-06-1998", Severity.error, "implausibly old"),
        ("05-06-2030", Severity.warning, "swapped"),
    ],
)
def test_date_violations_and_api_serialisation(
    checker: BusinessRuleChecker, valid_order: dict, po_date: str, severity: Severity, message: str
) -> None:
    valid_order["po_date"] = po_date
    violations = checker.check(PurchaseOrder.model_validate(valid_order))
    assert [v.severity for v in violations] == [severity]
    assert violations[0].field == "po_date"
    assert message in violations[0].message
    payload = violations[0].as_dict()
    assert set(payload) == {"field", "message", "severity"}
    assert payload["severity"] == severity.value


def test_duplicate_item_codes_warn(checker: BusinessRuleChecker, valid_order: dict) -> None:
    """The same part on two lines at different prices is legitimate."""
    second = {**valid_order["items"][0], "customer_number": "CT-9002"}
    valid_order["items"].append(second)

    violations = checker.check(PurchaseOrder.model_validate(valid_order))

    assert [v.severity for v in violations] == [Severity.warning]
    assert "TX703AR" in violations[0].message


def test_a_zero_priced_line_warns(checker: BusinessRuleChecker, valid_order: dict) -> None:
    valid_order["items"][0].update(unit_price=0, extension=0)

    violations = checker.check(PurchaseOrder.model_validate(valid_order))

    assert [v.severity for v in violations] == [Severity.warning]
    assert violations[0].field == "items.0.unit_price"


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
    # Without this, the model "fixes" a column shift by inventing a quantity.
    assert "column was read" in correction


def test_retries_stop_at_the_configured_budget(
    shifted_order: dict, parse_response: ParseResponse
) -> None:
    extractor = ScriptedExtractor([shifted_order])

    outcome = SelfHealingExtractor(extractor).extract(parse_response)

    assert outcome.attempts == 3, "1 initial attempt + LLM_SELF_HEAL_MAX_RETRIES"
    assert not outcome.is_valid
    assert outcome.healed is False
    assert len(extractor.corrections) == 3
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
