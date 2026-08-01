"""The harness end to end: sources, the runner's error handling, and the CLI."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.domain.schemas import ParseDecision, ParseResponse
from eval.labeled_set import EvalCase
from eval.run_eval import main
from eval.runner import EvalRunner
from eval.sources import LiveExtractionSource, ReplayExtractionSource, ScriptedExtractor


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

    assert (first, second) == ({"a": 1}, {"a": 2})
    assert extractor.corrections == [None, "fix"]


def test_the_last_scripted_answer_repeats() -> None:
    """A case listing one wrong answer models a document read wrong every time."""
    extractor = ScriptedExtractor([{"a": 1}])

    answers = [extractor.extract(None) for _ in range(3)]

    assert answers == [{"a": 1}] * 3


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

    source = LiveExtractionSource(parser, StubExtractor(), route_label="local")
    outcome = source.run(EvalCase(case_id="live1", expected=valid_order, document=document))

    assert source.name == "live-local"
    assert outcome.is_valid
    assert parser.calls == [(str(document), "eval_live1")]


def test_a_missing_document_is_reported(tmp_path: Path, valid_order: dict) -> None:
    source = LiveExtractionSource(RecordingParser(), None, route_label="local")

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


def test_the_json_report_holds_the_headline_numbers(tmp_path: Path) -> None:
    report_path = tmp_path / "eval.json"

    assert main(["--json", str(report_path)]) == EXIT_OK

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert len(payload["cases"]) == SYNTHETIC_CASE_COUNT
    assert payload["self_healing"]["recovery_rate"] == SYNTHETIC_RECOVERY_RATE
    assert len(payload["silent_failures"]) == SYNTHETIC_BLIND_SPOTS


def test_the_json_report_creates_missing_directories(tmp_path: Path) -> None:
    report_path = tmp_path / "nested" / "dir" / "eval.json"

    assert main(["--json", str(report_path)]) == EXIT_OK
    assert report_path.is_file()


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


def test_the_shipped_set_still_reports_its_known_blind_spots(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """These three are structural. If one disappears, the harness stopped seeing it."""
    main(["--json", str(tmp_path / "eval.json")])

    rendered = capsys.readouterr().out
    for case_id in ("dropped-line-item", "consistent-but-wrong", "null-extension-unverifiable"):
        assert case_id in rendered
    assert "Validation blind spots (3 case(s)" in rendered
