"""Accuracy evaluation for the extraction pipeline.

Run it with ``python -m eval.run_eval``.
"""
from __future__ import annotations

from eval.labeled_set import EvalCase, LabeledSet, LabeledSetError
from eval.report import EvalReport, RunContext
from eval.runner import CaseOutcome, EvalRunner
from eval.scoring import CaseScore, RecordScorer
from eval.sources import LiveExtractionSource, ReplayExtractionSource


__all__ = [
    "CaseOutcome",
    "CaseScore",
    "EvalCase",
    "EvalReport",
    "EvalRunner",
    "LabeledSet",
    "LabeledSetError",
    "LiveExtractionSource",
    "RecordScorer",
    "ReplayExtractionSource",
    "RunContext",
]
