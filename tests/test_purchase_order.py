"""The record's own invariants: a line must reconcile, a header must be present."""
from __future__ import annotations

import pytest
# pyrefly: ignore [missing-import]
from pydantic import ValidationError

from config.config import settings
from core.domain.purchase_order import PurchaseOrder


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
