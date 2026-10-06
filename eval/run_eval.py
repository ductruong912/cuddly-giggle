"""Score the extraction pipeline against the labeled set.

    python -m eval.run_eval                       # replay recorded answers
    python -m eval.run_eval --source local        # run the real local pipeline
    python -m eval.run_eval --json report.json --fail-under 0.95

Wiring only: the measuring lives in ``runner``, ``scoring`` and ``report``.
"""
from __future__ import annotations

import argparse
from contextlib import AbstractContextManager, nullcontext
import json
import logging
from pathlib import Path
import sys

from config.config import configure_app_logging, settings
from eval.labeled_set import EvalCase, LabeledSet, LabeledSetError
from eval.report import EvalReport, RunContext
from eval.runner import EvalRunner
from eval.sources import ExtractionSource, ReplayExtractionSource


logger = logging.getLogger(__name__)

DEFAULT_LABELED_SET = Path(__file__).resolve().parent / "labeled_set"
REPLAY_SOURCE = "replay"
EXIT_OK = 0
EXIT_BELOW_THRESHOLD = 1
EXIT_COULD_NOT_RUN = 2


def build_parser() -> argparse.ArgumentParser:
    """Define the command-line interface."""
    parser = argparse.ArgumentParser(
        prog="python -m eval.run_eval",
        description="Score extraction accuracy and self-healing against the labeled set.",
    )
    parser.add_argument(
        "--set",
        dest="labeled_set",
        type=Path,
        default=DEFAULT_LABELED_SET,
        help=f"directory of ground-truth manifests (default: {DEFAULT_LABELED_SET})",
    )
    parser.add_argument(
        "--source",
        choices=(REPLAY_SOURCE, "local"),
        default=REPLAY_SOURCE,
        help=(
            "replay recorded answers (default, needs no API key), or run the real "
            "pipeline over each case's document"
        ),
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        type=Path,
        help="also write the full report as JSON to this path",
    )
    parser.add_argument(
        "--fail-under",
        type=float,
        metavar="RATIO",
        help="exit non-zero when field accuracy falls below this ratio, e.g. 0.95",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Load the labeled set, run it, print the report, and return an exit code."""
    args = build_parser().parse_args(argv)
    configure_app_logging()

    try:
        cases = LabeledSet(args.labeled_set).load()
    except LabeledSetError as exc:
        logger.exception("the labeled set could not be loaded")
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_COULD_NOT_RUN

    selected = [case for case in cases if _matches_source(case, args.source)]
    skipped = len(cases) - len(selected)
    if not selected:
        print(
            f"error: no cases in {args.labeled_set} can run with the "
            f"'{args.source}' source ({skipped} skipped)",
            file=sys.stderr,
        )
        return EXIT_COULD_NOT_RUN

    with _source_for(args.source) as source:
        outcomes = EvalRunner(source).run(selected)
        context = RunContext(
            source_name=source.name,
            retry_budget=settings.llm_self_heal_max_retries,
            tolerance_ratio=settings.po_line_total_tolerance_ratio,
        )

    report = EvalReport(outcomes, context)
    print(report.render())
    if skipped:
        print(f"\nSkipped {skipped} case(s) not runnable with the '{args.source}' source.")

    if args.json_path:
        _write_json(report, args.json_path)
        print(f"Wrote {args.json_path}")

    if args.fail_under is not None and report.field_accuracy < args.fail_under:
        print(
            f"\nFAIL: field accuracy {report.field_accuracy:.1%} is below the "
            f"{args.fail_under:.1%} threshold",
            file=sys.stderr,
        )
        return EXIT_BELOW_THRESHOLD
    return EXIT_OK


def _matches_source(case: EvalCase, source: str) -> bool:
    """Replay runs need scripted answers; live runs need a document on disk."""
    return case.is_replay if source == REPLAY_SOURCE else not case.is_replay


def _source_for(source: str) -> AbstractContextManager[ExtractionSource]:
    """Return a context manager yielding the requested extraction source."""
    if source == REPLAY_SOURCE:
        return nullcontext(ReplayExtractionSource(settings))
    # Imported here so a replay run never pulls in the API stack or OCR engines.
    from eval.wiring import live_extraction_source

    return live_extraction_source()


def _write_json(report: EvalReport, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(report.as_dict(), handle, indent=2, ensure_ascii=False)
    except OSError:
        logger.exception("could not write the JSON report to %s", path)
        raise


if __name__ == "__main__":
    sys.exit(main())
