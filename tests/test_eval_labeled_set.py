"""Loading ground truth: a malformed labeled set must fail loudly, not quietly."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from eval.labeled_set import LabeledSet, LabeledSetError


RECORD = {
    "po_number": "1",
    "po_date": "01-06-2026",
    "items": [
        {
            "toto_number": "A1",
            "customer_number": "C1",
            "quantity": 2,
            "unit_price": 1000,
            "extension": 2000,
        }
    ],
}


def manifest_with(tmp_path: Path, *cases: dict, name: str = "cases.json") -> Path:
    (tmp_path / name).write_text(json.dumps({"cases": list(cases)}), encoding="utf-8")
    return tmp_path


def test_a_well_formed_case_loads(tmp_path: Path) -> None:
    root = manifest_with(
        tmp_path,
        {"case_id": "x", "expected": RECORD, "attempts": [RECORD], "description": "a case"},
    )

    cases = LabeledSet(root).load()

    assert len(cases) == 1
    assert cases[0].case_id == "x"
    assert cases[0].description == "a case"
    assert cases[0].is_replay is True


def test_cases_are_pooled_across_manifests(tmp_path: Path) -> None:
    """Real documents can be added alongside the synthetic set."""
    manifest_with(tmp_path, {"case_id": "a", "expected": RECORD, "attempts": [RECORD]},
                  name="synthetic.json")
    manifest_with(tmp_path, {"case_id": "b", "expected": RECORD, "attempts": [RECORD]},
                  name="real.json")

    assert {case.case_id for case in LabeledSet(tmp_path).load()} == {"a", "b"}


def test_a_document_path_resolves_against_its_manifest(tmp_path: Path) -> None:
    """So a labeled set stays portable when the repository moves."""
    root = manifest_with(tmp_path, {"case_id": "d", "expected": RECORD, "document": "docs/a.pdf"})

    case = LabeledSet(root).load()[0]

    assert case.is_replay is False
    assert case.document == (root / "docs" / "a.pdf").resolve()


def test_a_missing_directory_is_reported(tmp_path: Path) -> None:
    with pytest.raises(LabeledSetError, match="does not exist"):
        LabeledSet(tmp_path / "absent").load()


def test_a_directory_without_manifests_is_reported(tmp_path: Path) -> None:
    with pytest.raises(LabeledSetError, match=r"no \*\.json"):
        LabeledSet(tmp_path).load()


def test_unparseable_json_is_reported(tmp_path: Path) -> None:
    (tmp_path / "cases.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(LabeledSetError, match="not readable JSON"):
        LabeledSet(tmp_path).load()


def test_a_manifest_without_a_cases_list_is_reported(tmp_path: Path) -> None:
    (tmp_path / "cases.json").write_text(json.dumps({"nope": []}), encoding="utf-8")

    with pytest.raises(LabeledSetError, match="'cases' list"):
        LabeledSet(tmp_path).load()


@pytest.mark.parametrize(
    ("case", "expected_message"),
    [
        ({"expected": RECORD, "attempts": [RECORD]}, "no case_id"),
        ({"case_id": "x", "attempts": [RECORD]}, "no 'expected'"),
        ({"case_id": "x", "expected": RECORD}, "neither"),
        (
            {"case_id": "x", "expected": RECORD, "attempts": [RECORD], "document": "a.pdf"},
            "exactly one",
        ),
    ],
)
def test_a_malformed_case_is_reported(
    tmp_path: Path, case: dict, expected_message: str
) -> None:
    root = manifest_with(tmp_path, case)

    with pytest.raises(LabeledSetError, match=expected_message):
        LabeledSet(root).load()


def test_a_duplicate_case_id_is_reported(tmp_path: Path) -> None:
    """Two cases sharing an id would silently overwrite each other in the report."""
    root = manifest_with(
        tmp_path,
        {"case_id": "x", "expected": RECORD, "attempts": [RECORD]},
        {"case_id": "x", "expected": RECORD, "attempts": [RECORD]},
    )

    with pytest.raises(LabeledSetError, match="duplicate case_id"):
        LabeledSet(root).load()


def test_unreconcilable_ground_truth_warns_but_loads(tmp_path: Path, capture_logs) -> None:
    """A real document may genuinely state a total that does not add up.

    That caps the achievable validity rate, which is worth saying out loud, but
    it is not a reason to refuse to score the case.
    """
    broken = {**RECORD, "items": [{**RECORD["items"][0], "extension": 99999}]}
    root = manifest_with(tmp_path, {"case_id": "b", "expected": broken, "attempts": [broken]})

    with capture_logs("eval.labeled_set", logging.WARNING) as logs:
        cases = LabeledSet(root).load()

    assert len(cases) == 1
    assert "never be scored valid" in logs.getvalue()


def test_the_shipped_synthetic_set_loads() -> None:
    """The set the repository ships must stay loadable as the loader changes."""
    root = Path(__file__).resolve().parents[1] / "eval" / "labeled_set"

    cases = LabeledSet(root).load()

    assert len(cases) == 12
    assert all(case.is_replay for case in cases), "the shipped set needs no documents"
