"""Cross-field rules, and the error/warning split that decides what costs a retry."""
from __future__ import annotations

from datetime import date

import pytest

from core.domain.purchase_order import PurchaseOrder
from services.validation import BusinessRuleChecker, Severity


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


def test_violations_serialise_for_the_api(checker: BusinessRuleChecker, valid_order: dict) -> None:
    valid_order["po_date"] = "2026/06/05"

    payload = checker.check(order_from(valid_order))[0].as_dict()

    assert set(payload) == {"field", "message", "severity"}
    assert payload["severity"] == "error"
