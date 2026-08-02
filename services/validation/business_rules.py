"""Checks that go beyond the record's own invariants.

``PurchaseOrder`` enforces what must be true of a line in isolation. These rules
look at the record as a whole — date plausibility, repeated item codes — and
distinguish "the model got this wrong, ask again" from "a human should glance
at this".
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from core.domain.purchase_order import PurchaseOrder


PO_DATE_FORMAT = "%d-%m-%Y"
EARLIEST_PLAUSIBLE_YEAR = 2000
MAX_FUTURE_DAYS = 365


class Severity(str, Enum):
    """Whether a violation is worth another extraction attempt."""

    error = "error"
    warning = "warning"


@dataclass(frozen=True)
class RuleViolation:
    """One failed business rule, located at a field path."""

    field: str
    message: str
    severity: Severity

    def as_dict(self) -> dict[str, str]:
        return {"field": self.field, "message": self.message, "severity": self.severity.value}


class BusinessRuleChecker:
    """Apply the cross-field rules a single record cannot express on its own."""

    def __init__(self, today: date | None = None) -> None:
        # Injected so the plausibility window is testable without freezing time.
        self._today = today

    def check(self, order: PurchaseOrder) -> list[RuleViolation]:
        """Return every violation found, most actionable first."""
        violations: list[RuleViolation] = []
        violations.extend(self._check_date(order))
        violations.extend(self._check_duplicate_item_codes(order))
        violations.extend(self._check_zero_priced_lines(order))
        return violations

    def _check_date(self, order: PurchaseOrder) -> list[RuleViolation]:
        try:
            parsed = datetime.strptime(order.po_date.strip(), PO_DATE_FORMAT).date()
        except ValueError:
            return [
                RuleViolation(
                    field="po_date",
                    message=(
                        f"po_date {order.po_date!r} is not in DD-MM-YYYY format. "
                        "Re-read the date on the document and reformat it."
                    ),
                    severity=Severity.error,
                )
            ]

        today = self._today or date.today()
        if parsed.year < EARLIEST_PLAUSIBLE_YEAR:
            return [
                RuleViolation(
                    field="po_date",
                    message=f"po_date {parsed.isoformat()} is implausibly old; check the year.",
                    severity=Severity.error,
                )
            ]
        if (parsed - today).days > MAX_FUTURE_DAYS:
            return [
                RuleViolation(
                    field="po_date",
                    message=(
                        f"po_date {parsed.isoformat()} is more than a year in the future; "
                        "the day and month may be swapped."
                    ),
                    severity=Severity.warning,
                )
            ]
        return []

    @staticmethod
    def _check_duplicate_item_codes(order: PurchaseOrder) -> list[RuleViolation]:
        counts = Counter(item.toto_number.strip() for item in order.items)
        # A repeated code can be legitimate (the same part on two lines with
        # different prices), so this is a prompt for review, not a retry.
        return [
            RuleViolation(
                field="items",
                message=f"toto_number {code!r} appears on {count} lines; check they are not OCR duplicates.",
                severity=Severity.warning,
            )
            for code, count in sorted(counts.items())
            if count > 1
        ]

    @staticmethod
    def _check_zero_priced_lines(order: PurchaseOrder) -> list[RuleViolation]:
        return [
            RuleViolation(
                field=f"items.{index}.unit_price",
                message=f"unit_price is zero for item {item.toto_number!r}; confirm the price column was read.",
                severity=Severity.warning,
            )
            for index, item in enumerate(order.items)
            if item.unit_price == 0
        ]
