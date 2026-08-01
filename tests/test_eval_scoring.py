"""Field-level comparison, and matching line items by code rather than position."""
from __future__ import annotations

import pytest

from eval.scoring import RecordScorer


ITEM = {
    "toto_number": "A1",
    "customer_number": "C1",
    "quantity": 2,
    "unit_price": 1000,
    "extension": 2000,
}
RECORD = {"po_number": "1", "po_date": "01-06-2026", "items": [ITEM]}


@pytest.fixture
def scorer() -> RecordScorer:
    return RecordScorer()


def with_items(*items: dict) -> dict:
    return {**RECORD, "items": list(items)}


def test_identical_records_score_exact(scorer: RecordScorer) -> None:
    score = scorer.score("c", RECORD, RECORD)

    assert score.is_exact
    assert score.accuracy == 1.0
    assert score.total_fields == 7, "2 header fields + 5 per line item"


def test_json_number_forms_are_not_disagreement(scorer: RecordScorer) -> None:
    """500000 and 500000.0 are the same figure, differently round-tripped."""
    floaty = with_items({**ITEM, "quantity": 2.0, "extension": 2000.0})

    assert scorer.score("c", RECORD, floaty).is_exact


def test_surrounding_whitespace_is_ignored(scorer: RecordScorer) -> None:
    assert scorer.score("c", RECORD, {**RECORD, "po_number": " 1 "}).is_exact


def test_a_wrong_field_is_named(scorer: RecordScorer) -> None:
    score = scorer.score("c", RECORD, {**RECORD, "po_number": "2"})

    assert [result.field for result in score.wrong_fields] == ["po_number"]
    assert not score.is_exact


def test_item_order_does_not_matter(scorer: RecordScorer) -> None:
    """Items are matched by code, so a reordered answer is not penalised."""
    second = {**ITEM, "toto_number": "A2"}

    assert scorer.score("c", with_items(ITEM, second), with_items(second, ITEM)).is_exact


def test_a_dropped_item_costs_all_of_its_fields(scorer: RecordScorer) -> None:
    """Counting only the item code would make losing a row look cheap."""
    expected = with_items(ITEM, {**ITEM, "toto_number": "A2"}, {**ITEM, "toto_number": "A3"})
    actual = with_items(ITEM, {**ITEM, "toto_number": "A2"})

    score = scorer.score("c", expected, actual)

    assert score.missed_items == ["A3"]
    assert (score.correct_fields, score.total_fields) == (12, 17)
    assert not score.is_exact


def test_an_invented_item_is_reported(scorer: RecordScorer) -> None:
    expected = with_items(ITEM)
    actual = with_items(ITEM, {**ITEM, "toto_number": "A9"})

    score = scorer.score("c", expected, actual)

    assert score.spurious_items == ["A9"]
    assert not score.is_exact


def test_a_dropped_row_does_not_misalign_the_rest(scorer: RecordScorer) -> None:
    """Position-based matching would mark every later row wrong as well."""
    expected = with_items(
        {**ITEM, "toto_number": "A1"},
        {**ITEM, "toto_number": "A2", "quantity": 7},
        {**ITEM, "toto_number": "A3", "quantity": 9},
    )
    actual = with_items(
        {**ITEM, "toto_number": "A2", "quantity": 7},
        {**ITEM, "toto_number": "A3", "quantity": 9},
    )

    score = scorer.score("c", expected, actual)

    assert score.missed_items == ["A1"]
    assert score.correct_fields == 12, "only the dropped row's five fields are lost"


def test_repeated_codes_align_in_order(scorer: RecordScorer) -> None:
    """The same part on two lines is legitimate; matching must not collapse them."""
    expected = with_items(ITEM, {**ITEM, "customer_number": "C2"})

    assert scorer.score("c", expected, expected).is_exact


def test_swapped_repeated_codes_cost_only_the_differing_field(scorer: RecordScorer) -> None:
    expected = with_items(ITEM, {**ITEM, "customer_number": "C2"})
    actual = with_items({**ITEM, "customer_number": "C2"}, ITEM)

    score = scorer.score("c", expected, actual)

    assert score.correct_fields == 10
    assert [result.field.rsplit(".", 1)[-1] for result in score.wrong_fields] == [
        "customer_number"
    ] * 2


def test_null_matches_null(scorer: RecordScorer) -> None:
    """Documents that print no line total legitimately extract as null."""
    nulled = with_items({**ITEM, "extension": None})

    assert scorer.score("c", nulled, nulled).is_exact


def test_a_value_replaced_by_null_is_wrong(scorer: RecordScorer) -> None:
    score = scorer.score("c", RECORD, with_items({**ITEM, "extension": None}))

    assert score.correct_fields == 6
    assert not score.is_exact


def test_an_empty_extraction_scores_zero(scorer: RecordScorer) -> None:
    score = scorer.score("c", RECORD, {})

    assert score.accuracy == 0.0
    assert score.missed_items == ["A1"]


def test_a_malformed_items_field_is_survivable(scorer: RecordScorer) -> None:
    """A failed extraction must be scorable, not raise inside the harness."""
    score = scorer.score("c", RECORD, {**RECORD, "items": "not-a-list"})

    assert score.missed_items == ["A1"]
    assert not score.is_exact
