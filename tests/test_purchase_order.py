"""Purchase-order invariants, business rules and the generated LLM schema."""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from config.config import settings
from core.domain.purchase_order import PurchaseOrder
from core.domain.strict_schema import (
    UNSUPPORTED_KEYWORDS,
    assert_strict_schema,
    to_strict_json_schema,
)
from core.prompts.prompt import EXTRACTION_JSON_SCHEMA
from services.validation import BusinessRuleChecker, Severity


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


TODAY = date(2026, 8, 1)


@pytest.fixture
def checker() -> BusinessRuleChecker:
    """A checker with time frozen, so the plausibility window never drifts."""
    return BusinessRuleChecker(today=TODAY)


def order_from(payload: dict) -> PurchaseOrder:
    return PurchaseOrder.model_validate(payload)


def test_a_clean_order_has_no_violations(checker: BusinessRuleChecker, valid_order: dict) -> None:
    assert checker.check(order_from(valid_order)) == []


def test_a_misformatted_date_is_an_error(checker: BusinessRuleChecker, valid_order: dict) -> None:
    valid_order["po_date"] = "2026/06/05"

    violations = checker.check(order_from(valid_order))

    assert [v.severity for v in violations] == [Severity.error]
    assert violations[0].field == "po_date"
    assert "DD-MM-YYYY" in violations[0].message
    assert set(violations[0].as_dict()) == {"field", "message", "severity"}
    assert violations[0].as_dict()["severity"] == "error"


def test_an_implausibly_old_date_is_an_error(checker: BusinessRuleChecker, valid_order: dict) -> None:
    valid_order["po_date"] = "05-06-1998"

    violations = checker.check(order_from(valid_order))

    assert [v.severity for v in violations] == [Severity.error]
    assert "implausibly old" in violations[0].message


def test_a_far_future_date_is_only_a_warning(checker: BusinessRuleChecker, valid_order: dict) -> None:
    """A swapped day and month is worth a human glance, not another extraction."""
    valid_order["po_date"] = "05-06-2030"

    violations = checker.check(order_from(valid_order))

    assert [v.severity for v in violations] == [Severity.warning]
    assert "swapped" in violations[0].message


def test_a_date_inside_the_window_passes(checker: BusinessRuleChecker, valid_order: dict) -> None:
    valid_order["po_date"] = "01-07-2027"

    assert checker.check(order_from(valid_order)) == []


def test_duplicate_item_codes_warn(checker: BusinessRuleChecker, valid_order: dict) -> None:
    """The same part on two lines at different prices is legitimate."""
    second = {**valid_order["items"][0], "customer_number": "CT-9002"}
    valid_order["items"].append(second)

    violations = checker.check(order_from(valid_order))

    assert [v.severity for v in violations] == [Severity.warning]
    assert "TX703AR" in violations[0].message


def test_a_zero_priced_line_warns(checker: BusinessRuleChecker, valid_order: dict) -> None:
    valid_order["items"][0].update(unit_price=0, extension=0)

    violations = checker.check(order_from(valid_order))

    assert [v.severity for v in violations] == [Severity.warning]
    assert violations[0].field == "items.0.unit_price"


def test_the_shipped_schema_is_generated_from_the_model() -> None:
    assert EXTRACTION_JSON_SCHEMA == to_strict_json_schema(PurchaseOrder)
    assert_strict_schema(EXTRACTION_JSON_SCHEMA)

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                assert set(node.get("required", [])) == set(node.get("properties", {}))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(EXTRACTION_JSON_SCHEMA)
    item_schema = EXTRACTION_JSON_SCHEMA["$defs"]["PurchaseOrderItem"]
    assert set(item_schema["properties"]) == {
        "toto_number", "customer_number", "quantity", "unit_price", "extension",
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
