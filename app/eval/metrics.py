from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
import math
import re


def _levenshtein(a: Sequence, b: Sequence) -> int:
    # Works on any sequence: a str (character-level, used by cer) or a list of
    # word tokens (word-level, used by wer).
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    curr = [0] * (len(b) + 1)
    for i, ca in enumerate(a, start=1):
        curr[0] = i
        for j, cb in enumerate(b, start=1):
            ins = curr[j - 1] + 1
            dele = prev[j] + 1
            subs = prev[j - 1] + (0 if ca == cb else 1)
            curr[j] = min(ins, dele, subs)
        prev, curr = curr, prev
    return prev[-1]


def cer(pred: str, gt: str) -> float:
    if not gt:
        return 0.0 if not pred else 1.0
    return _levenshtein(pred, gt) / len(gt)


def wer(pred: str, gt: str) -> float:
    gt_words = gt.split()
    pred_words = pred.split()
    if not gt_words:
        return 0.0 if not pred_words else 1.0
    # Edit distance over WORD tokens divided by the word count — a real WER.
    # (The old code ran a character-level distance over joined strings but still
    # divided by word count, so the result was unbounded and not a word error rate.)
    return _levenshtein(pred_words, gt_words) / len(gt_words)


@dataclass
class PrecisionRecallF1:
    precision: float
    recall: float
    f1: float


def prf(tp: int, fp: int, fn: int) -> PrecisionRecallF1:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return PrecisionRecallF1(precision=precision, recall=recall, f1=f1)


def table_cell_f1(pred_cells: list[str], gt_cells: list[str]) -> PrecisionRecallF1:
    # Multiset (Counter) semantics so repeated cell values — common in OCR tables
    # (zeros, dates, amounts, repeated labels) — count individually instead of
    # collapsing to one, which would inflate F1 and hide missed/duplicated cells.
    pred_counts = Counter(normalize_cell_text(v) for v in pred_cells if v.strip())
    gt_counts = Counter(normalize_cell_text(v) for v in gt_cells if v.strip())
    tp = sum((pred_counts & gt_counts).values())
    fp = sum((pred_counts - gt_counts).values())
    fn = sum((gt_counts - pred_counts).values())
    return prf(tp, fp, fn)


def normalize_cell_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("vnđ", "vnd")
    return text


def exact_match(pred: str, gt: str) -> float:
    return 1.0 if pred.strip() == gt.strip() else 0.0


def mean(values: list[float]) -> float:
    if not values:
        return math.nan
    return sum(values) / len(values)