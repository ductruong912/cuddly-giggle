# Labeled set

Ground truth for `python -m eval.run_eval`. Every `*.json` file in this directory
is loaded and its `cases` are concatenated, so real documents can be added
alongside the synthetic set without touching it.

## What is here today

`synthetic.json` holds **12 hand-written cases. They are not real documents.**
They exist so the harness reports real numbers before a document corpus exists,
and they measure exactly one thing: the validation and self-healing layer.

They cannot tell you anything about OCR accuracy, and the accuracy figure they
produce is a property of the fixtures, not of the pipeline. Replace them — or
better, add to them — as soon as real purchase orders are available.

## Case format

A case is either a **replay** case or a **document** case. It must set exactly
one of `attempts` or `document`.

```jsonc
{
  "cases": [
    {
      "case_id": "unique-id",           // required, unique across every manifest
      "description": "what it covers",  // optional, shown in the report
      "expected": { ... },              // required: the ground-truth PurchaseOrder

      // Replay case: recorded model answers, one per attempt.
      "attempts": [ { ... }, { ... } ],

      // Document case: path to a file, relative to this manifest.
      "document": "documents/po-215497.pdf"
    }
  ]
}
```

`expected` uses the `PurchaseOrder` shape: `po_number`, `po_date` (DD-MM-YYYY),
and `items[]` of `toto_number`, `customer_number`, `quantity`, `unit_price`,
`extension`. Use `null` for `extension` when the document does not print a line
total, and for `customer_number` when there is no second code.

If a ground-truth record does not itself satisfy `PurchaseOrder`, the loader logs
a warning and scores the case anyway. That happens when a real document states a
line total that genuinely does not reconcile — worth knowing, because such a case
can never be scored valid.

### Replay cases

`attempts` is consumed one entry per extraction call, and the **last entry
repeats forever**. So:

- one entry that is wrong → the model never corrects itself → `needs_review`
- a wrong entry then a right one → measures recovery
- one entry that is right → a clean first-pass extraction

The number of attempts actually reached depends on `LLM_SELF_HEAL_MAX_RETRIES`;
the report prints the budget it ran with.

### Document cases

```
eval/labeled_set/
├── real.json
└── documents/
    ├── po-215497.pdf
    └── po-215612.pdf
```

Run them with `--source local`. This calls the local OCR engine and the real
OpenAI API, so it costs money and needs `OPENAI_API_KEY`.

`--source replay` skips document cases and vice versa; the report says how many
were skipped.

## Adding real documents

1. Drop the files in `documents/`.
2. Create `real.json` with one case per document and its `expected` record.
3. Run `python -m eval.run_eval --source local --json outputs/eval.json`.

Twenty to thirty documents is the range the implementation plan asks for. Bias
the selection toward the layouts that actually fail today rather than the clean
ones — the clean ones are already at 100%.

Label from the document itself, not from pipeline output. Ground truth derived
from a run measures self-consistency, not accuracy.
