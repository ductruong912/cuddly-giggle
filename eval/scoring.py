"""Compare an extracted record against ground truth, field by field.

Line items are matched by item code rather than by position, so one dropped row
costs one row instead of misaligning every row after it.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import logging
import math
from typing import Any


logger = logging.getLogger(__name__)

HEADER_FIELDS = ("po_number", "po_date")
ITEM_FIELDS = ("toto_number", "customer_number", "quantity", "unit_price", "extension")
NUMERIC_FIELDS = frozenset({"quantity", "unit_price", "extension"})
ITEM_KEY_FIELD = "toto_number"
# Both sides arrive as JSON, so this only absorbs float round-tripping (500000 vs
# 500000.0), never genuine disagreement.
NUMERIC_RELATIVE_TOLERANCE = 1e-9


@dataclass(frozen=True)
class FieldResult:
    """One compared field, and whether the extraction got it right."""

    field: str
    expected: Any
    actual: Any
    correct: bool


@dataclass(frozen=True)
class CaseScore:
    """Field-level agreement between one extraction and its ground truth."""

    case_id: str
    fields: list[FieldResult]
    missed_items: list[str]
    spurious_items: list[str]

    @property
    def total_fields(self) -> int:
        return len(self.fields)

    @property
    def correct_fields(self) -> int:
        return sum(1 for result in self.fields if result.correct)

    @property
    def accuracy(self) -> float:
        """Fraction of ground-truth fields reproduced exactly."""
        return self.correct_fields / self.total_fields if self.total_fields else 0.0

    @property
    def is_exact(self) -> bool:
        """True when every field matched and no line item was dropped or invented."""
        return (
            not self.missed_items
            and not self.spurious_items
            and self.correct_fields == self.total_fields
        )

    @property
    def wrong_fields(self) -> list[FieldResult]:
        return [result for result in self.fields if not result.correct]


class RecordScorer:
    """Score an extracted purchase order against the expected one."""

    def score(
        self,
        case_id: str,
        expected: dict[str, Any],
        actual: dict[str, Any],
    ) -> CaseScore:
        """Compare header and line-item fields and report where they diverged.

        Args:
            case_id: identifier carried through to the report.
            expected: the ground-truth record.
            actual: whatever the extraction produced, valid or not.
        """
        results = [
            self._compare(name, expected.get(name), actual.get(name))
            for name in HEADER_FIELDS
        ]

        expected_items = self._items(expected)
        actual_items = self._items(actual)
        matched, missed, spurious = self._align_items(expected_items, actual_items)

        for expected_item, actual_item in matched:
            label = self._item_label(expected_item)
            results.extend(
                self._compare(
                    f"{label}.{name}", expected_item.get(name), actual_item.get(name)
                )
                for name in ITEM_FIELDS
            )

        # A dropped row is a miss on every one of its fields; counting only the
        # item code would make losing a row look cheaper than misreading one.
        for expected_item in missed:
            label = self._item_label(expected_item)
            results.extend(
                FieldResult(
                    field=f"{label}.{name}",
                    expected=expected_item.get(name),
                    actual=None,
                    correct=False,
                )
                for name in ITEM_FIELDS
            )

        return CaseScore(
            case_id=case_id,
            fields=results,
            missed_items=[self._item_key(item) for item in missed],
            spurious_items=[self._item_key(item) for item in spurious],
        )

    @staticmethod
    def _items(record: dict[str, Any]) -> list[dict[str, Any]]:
        items = record.get("items")
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    @classmethod
    def _align_items(
        cls,
        expected_items: list[dict[str, Any]],
        actual_items: list[dict[str, Any]],
    ) -> tuple[
        list[tuple[dict[str, Any], dict[str, Any]]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        """Pair expected items with predicted ones by item code, first-come first-served."""
        pending: dict[str, deque[dict[str, Any]]] = {}
        for item in actual_items:
            pending.setdefault(cls._item_key(item), deque()).append(item)

        matched: list[tuple[dict[str, Any], dict[str, Any]]] = []
        missed: list[dict[str, Any]] = []
        for expected_item in expected_items:
            queue = pending.get(cls._item_key(expected_item))
            if queue:
                matched.append((expected_item, queue.popleft()))
            else:
                missed.append(expected_item)

        spurious = [item for queue in pending.values() for item in queue]
        return matched, missed, spurious

    @classmethod
    def _compare(cls, field_name: str, expected: Any, actual: Any) -> FieldResult:
        return FieldResult(
            field=field_name,
            expected=expected,
            actual=actual,
            correct=cls._values_match(field_name, expected, actual),
        )

    @classmethod
    def _values_match(cls, field_name: str, expected: Any, actual: Any) -> bool:
        if expected is None or actual is None:
            return expected is None and actual is None
        if cls._bare_name(field_name) in NUMERIC_FIELDS:
            return cls._numbers_match(expected, actual)
        return str(expected).strip() == str(actual).strip()

    @staticmethod
    def _numbers_match(expected: Any, actual: Any) -> bool:
        try:
            return math.isclose(
                float(expected),
                float(actual),
                rel_tol=NUMERIC_RELATIVE_TOLERANCE,
                abs_tol=NUMERIC_RELATIVE_TOLERANCE,
            )
        except (TypeError, ValueError):
            logger.exception("could not compare %r with %r numerically", expected, actual)
            return False

    @staticmethod
    def _bare_name(field_name: str) -> str:
        """``items[TX703AR].quantity`` -> ``quantity``."""
        return field_name.rsplit(".", 1)[-1]

    @classmethod
    def _item_label(cls, item: dict[str, Any]) -> str:
        return f"items[{cls._item_key(item) or '?'}]"

    @staticmethod
    def _item_key(item: dict[str, Any]) -> str:
        return str(item.get(ITEM_KEY_FIELD, "")).strip()
