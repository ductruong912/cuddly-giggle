from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.eval.metrics import cer, exact_match, mean, table_cell_f1, wer


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def flatten_blocks_text(page: dict[str, Any]) -> str:
    blocks = page.get("blocks", [])
    if not isinstance(blocks, list):
        return ""
    chunks = []
    for block in blocks:
        if isinstance(block, dict):
            chunks.append(str(block.get("content", "")))
    return "\n".join([c for c in chunks if c.strip()])


def flatten_table_cells(page: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for table in page.get("tables", []):
        if not isinstance(table, dict):
            continue
        for cell in table.get("cells", []):
            if isinstance(cell, dict):
                out.append(str(cell.get("text", "")))
    return out


def reading_order_accuracy(pred: list[str], gt: list[str]) -> float:
    if not gt:
        return 1.0 if not pred else 0.0
    hits = 0
    for idx, item in enumerate(gt):
        if idx < len(pred) and pred[idx] == item:
            hits += 1
    return hits / len(gt)


def evaluate(gt: dict[str, Any], pred: dict[str, Any]) -> dict[str, float]:
    gt_pages = gt.get("pages", [])
    pred_pages = pred.get("pages", [])

    cer_scores: list[float] = []
    wer_scores: list[float] = []
    table_f1_scores: list[float] = []
    ro_scores: list[float] = []
    field_em_scores: list[float] = []

    for idx, gt_page in enumerate(gt_pages):
        if not isinstance(gt_page, dict):
            continue
        pred_page = pred_pages[idx] if idx < len(pred_pages) and isinstance(pred_pages[idx], dict) else {}

        gt_text = str(gt_page.get("text", ""))
        pred_text = flatten_blocks_text(pred_page)
        cer_scores.append(cer(pred_text, gt_text))
        wer_scores.append(wer(pred_text, gt_text))

        gt_cells = gt_page.get("cells", []) if isinstance(gt_page.get("cells"), list) else []
        pred_cells = flatten_table_cells(pred_page)
        table_f1_scores.append(table_cell_f1(pred_cells, [str(x) for x in gt_cells]).f1)

        gt_ro = gt_page.get("reading_order", []) if isinstance(gt_page.get("reading_order"), list) else []
        pred_ro = pred_page.get("reading_order", []) if isinstance(pred_page.get("reading_order"), list) else []
        ro_scores.append(reading_order_accuracy([str(x) for x in pred_ro], [str(x) for x in gt_ro]))

        gt_fields = gt_page.get("fields", {}) if isinstance(gt_page.get("fields"), dict) else {}
        pred_fields = pred_page.get("fields", {}) if isinstance(pred_page.get("fields"), dict) else {}
        for key, gt_val in gt_fields.items():
            field_em_scores.append(exact_match(str(pred_fields.get(key, "")), str(gt_val)))

    return {
        "cer_avg": mean(cer_scores),
        "wer_avg": mean(wer_scores),
        "table_f1_avg": mean(table_f1_scores),
        "reading_order_acc_avg": mean(ro_scores),
        "field_exact_match_avg": mean(field_em_scores) if field_em_scores else float("nan"),
        "num_pages": float(len(gt_pages)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Acceptance evaluation for OCR extraction.")
    parser.add_argument("--ground-truth", required=True, help="Path to normalized ground truth JSON.")
    parser.add_argument("--prediction", required=True, help="Path to normalized prediction JSON.")
    args = parser.parse_args()

    gt = load_json(Path(args.ground_truth))
    pred = load_json(Path(args.prediction))
    report = evaluate(gt, pred)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()