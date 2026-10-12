"""Labeled sets, field scoring, aggregate reports, replay and the evaluation CLI."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from eval.report import EvalReport, RunContext
from eval.runner import CaseOutcome, EvalRunner
from eval.scoring import CaseScore, FieldResult, RecordScorer
from eval.labeled_set import LabeledSet, LabeledSetError, EvalCase
from core.domain.schemas import ParseDecision, ParseResponse
from eval.run_eval import main
from eval.sources import LiveExtractionSource, ReplayExtractionSource, ScriptedExtractor


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


def test_mixed_run_metrics_and_review_classification(mixed_run: list, context: RunContext) -> None:
    report = EvalReport(mixed_run, context)

    assert (report.correct_fields, report.total_fields) == (13, 16)
    assert report.field_accuracy == pytest.approx(13 / 16)
    assert {o.case_id for o in report.initially_invalid} == {"healed", "failed"}
    assert report.recovery_rate == 0.5
    assert [o.case_id for o in report.needs_review] == ["failed"]
    assert [o.case_id for o in report.silent_failures] == ["silent"]
    assert report.mean_attempts == 1.75


def test_the_recovery_rate_is_zero_when_nothing_failed(context: RunContext) -> None:
    clean = [make_outcome(f"c{i}", correct=4, total=4, attempts=1, is_valid=True) for i in range(3)]

    report = EvalReport(clean, context)

    assert report.recovery_rate == 0.0
    assert report.field_accuracy == 1.0
    assert report.silent_failures == []


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
    assert payload["settings"] == {"self_heal_retry_budget": 2, "line_total_tolerance_ratio": 0.01}


def test_an_errored_case_is_shown_as_an_error(context: RunContext) -> None:
    errored = make_outcome(
        "boom", correct=0, total=4, attempts=0, is_valid=False, exact=False,
        error="OSError: unreadable",
    )

    rendered = EvalReport([errored], context).render()

    assert "error" in rendered and "OSError" in rendered


LABELED_RECORD = {
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
        {"case_id": "x", "expected": LABELED_RECORD, "attempts": [LABELED_RECORD], "description": "a case"},
    )

    cases = LabeledSet(root).load()

    assert len(cases) == 1
    assert cases[0].case_id == "x"
    assert cases[0].description == "a case"
    assert cases[0].is_replay is True


def test_cases_are_pooled_across_manifests(tmp_path: Path) -> None:
    """Real documents can be added alongside the synthetic set."""
    manifest_with(tmp_path, {"case_id": "a", "expected": LABELED_RECORD, "attempts": [LABELED_RECORD]},
                  name="synthetic.json")
    manifest_with(tmp_path, {"case_id": "b", "expected": LABELED_RECORD, "attempts": [LABELED_RECORD]},
                  name="real.json")

    assert {case.case_id for case in LabeledSet(tmp_path).load()} == {"a", "b"}


def test_a_document_path_resolves_against_its_manifest(tmp_path: Path) -> None:
    """So a labeled set stays portable when the repository moves."""
    root = manifest_with(tmp_path, {"case_id": "d", "expected": LABELED_RECORD, "document": "docs/a.pdf"})

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
        ({"expected": LABELED_RECORD, "attempts": [LABELED_RECORD]}, "no case_id"),
        ({"case_id": "x", "attempts": [LABELED_RECORD]}, "no 'expected'"),
        ({"case_id": "x", "expected": LABELED_RECORD}, "neither"),
        (
            {"case_id": "x", "expected": LABELED_RECORD, "attempts": [LABELED_RECORD], "document": "a.pdf"},
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
        {"case_id": "x", "expected": LABELED_RECORD, "attempts": [LABELED_RECORD]},
        {"case_id": "x", "expected": LABELED_RECORD, "attempts": [LABELED_RECORD]},
    )

    with pytest.raises(LabeledSetError, match="duplicate case_id"):
        LabeledSet(root).load()


def test_unreconcilable_ground_truth_warns_but_loads(tmp_path: Path, capture_logs) -> None:
    """A real document may genuinely state a total that does not add up.

    That caps the achievable validity rate, which is worth saying out loud, but
    it is not a reason to refuse to score the case.
    """
    broken = {**LABELED_RECORD, "items": [{**LABELED_RECORD["items"][0], "extension": 99999}]}
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


EXIT_OK = 0
EXIT_BELOW_THRESHOLD = 1
EXIT_COULD_NOT_RUN = 2

SYNTHETIC_CASE_COUNT = 12
SYNTHETIC_RECOVERY_RATE = 0.75
SYNTHETIC_BLIND_SPOTS = 3


# -- sources -----------------------------------------------------------------

def test_scripted_answers_are_returned_in_order() -> None:
    extractor = ScriptedExtractor([{"a": 1}, {"a": 2}])

    first = extractor.extract(None, correction=None)
    second = extractor.extract(None, correction="fix")
    repeated = extractor.extract(None)

    assert (first, second) == ({"a": 1}, {"a": 2})
    assert repeated == second
    assert extractor.corrections == [None, "fix", None]


def test_replay_drives_the_real_self_heal_loop(valid_order: dict) -> None:
    outcome = ReplayExtractionSource().run(
        EvalCase(case_id="r", expected=valid_order, attempts=[valid_order])
    )

    assert outcome.is_valid
    assert outcome.attempts == 1


def test_a_replay_case_without_answers_is_rejected(valid_order: dict) -> None:
    with pytest.raises(ValueError, match="no recorded attempts"):
        ReplayExtractionSource().run(EvalCase(case_id="e", expected=valid_order, attempts=[]))


class RecordingParser:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def parse(self, input_path: str, *, request_id: str | None = None) -> ParseResponse:
        self.calls.append((input_path, request_id))
        return ParseResponse(
            request_id=request_id or "req",
            decision=ParseDecision(reason="stub"),
            pages=[], blocks=[], tables=[], reading_order=[], markdown="# doc",
        )


def test_the_live_source_parses_then_validates(tmp_path: Path, valid_order: dict) -> None:
    document = tmp_path / "po.pdf"
    document.write_bytes(b"%PDF-1.4")
    parser = RecordingParser()

    class StubExtractor:
        def extract(self, parse_response, *, correction=None):
            return valid_order

    source = LiveExtractionSource(parser, StubExtractor())
    outcome = source.run(EvalCase(case_id="live1", expected=valid_order, document=document))

    assert source.name == "live-local"
    assert outcome.is_valid
    assert parser.calls == [(str(document), "eval_live1")]


def test_a_missing_document_is_reported(tmp_path: Path, valid_order: dict) -> None:
    source = LiveExtractionSource(RecordingParser(), None)

    with pytest.raises(FileNotFoundError, match="absent.pdf"):
        source.run(
            EvalCase(case_id="g", expected=valid_order, document=tmp_path / "absent.pdf")
        )


# -- runner ------------------------------------------------------------------

def test_a_failing_case_does_not_abort_the_run(valid_order: dict) -> None:
    """One unreadable document must not cost the other twenty-nine."""

    class Exploding:
        name = "exploding"

        def run(self, case):
            raise OSError("document unreadable")

    outcomes = EvalRunner(Exploding()).run(
        [EvalCase(case_id="x", expected=valid_order, attempts=[valid_order])]
    )

    assert len(outcomes) == 1
    assert "document unreadable" in (outcomes[0].error or "")
    assert outcomes[0].score.accuracy == 0.0
    assert outcomes[0].is_valid is False


# -- command line ------------------------------------------------------------

def test_a_default_run_succeeds() -> None:
    assert main([]) == EXIT_OK


def test_cli_reports_metrics_and_blind_spots_in_a_new_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    report_path = tmp_path / "nested" / "dir" / "eval.json"

    assert main(["--json", str(report_path)]) == EXIT_OK

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert len(payload["cases"]) == SYNTHETIC_CASE_COUNT
    assert payload["self_healing"]["recovery_rate"] == SYNTHETIC_RECOVERY_RATE
    assert len(payload["silent_failures"]) == SYNTHETIC_BLIND_SPOTS
    rendered = capsys.readouterr().out
    for case_id in ("dropped-line-item", "consistent-but-wrong", "null-extension-unverifiable"):
        assert case_id in rendered
    assert "Validation blind spots (3 case(s)" in rendered


def test_fail_under_gates_on_accuracy() -> None:
    """The CI gate: an accuracy regression fails a build."""
    assert main(["--fail-under", "0.99"]) == EXIT_BELOW_THRESHOLD
    assert main(["--fail-under", "0.90"]) == EXIT_OK


def test_a_missing_labeled_set_exits_distinctly(tmp_path: Path) -> None:
    """Exit 2 means 'could not run', which is not the same as 'scored badly'."""
    assert main(["--set", str(tmp_path / "absent")]) == EXIT_COULD_NOT_RUN


def test_a_live_run_with_no_documents_exits_distinctly() -> None:
    """The shipped set is replay-only, so a live run has nothing to do."""
    assert main(["--source", "local"]) == EXIT_COULD_NOT_RUN
