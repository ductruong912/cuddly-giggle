# Gap Analysis — Implementation Plan vs. Current Code

Written 2026-08-01, against the repo state after the concurrency/production review.
Updated the same day, twice: after the validation layer, then after the eval harness.
Companion to `project2_ocr_pipeline_implementation_plan.md`.

**Short version:** the OCR half of the plan is built and in places exceeds it.
Deterministic validation, self-healing and the eval harness are now built too.
What remains missing is persistence, queueing and human review — and a **real
labeled set**, which is now the binding constraint on everything else. The
harness runs and reports, but against synthetic fixtures; until real documents
are labeled, its accuracy figure measures the fixtures rather than the pipeline.

---

## 1. Component status

Legend: **Done** · **Partial** · **Missing** · *N/A (deliberately diverged)*

### Preprocessing & OCR — largely done

| Plan component | Status | Notes |
|---|---|---|
| `preprocessing/text_layer.py` (Tier 0) | **Done, exceeds plan** | `core/engines/native/pdf_text.py`. The plan asked for a `total_chars >= 50` check; the code also rejects garbled glyph runs (private-use codepoints) and broken font cmaps (`Nguy6n`-style digit corruption), which a naive char count would wave through. |
| Word / Excel native extraction | **Done, not in plan** | `word_text.py`, `excel_text.py`, incl. LibreOffice conversion for legacy `.doc`/`.xls`. |
| `preprocessing/image_prep.py` (OpenCV deskew/binarize/denoise) | **Missing** | Pages are rasterized at 200 DPI and passed to OCR unprocessed. `opencv-contrib-python` is already installed as a paddlex dependency. |
| `preprocessing/quality_score.py` | **Missing** | Nothing measures DPI, whitespace ratio or column count. |
| `ocr/fast_tier.py` (PaddleOCR CPU) | **Done** | `paddle_fast.py`, PP-OCRv6 via ONNX Runtime. |
| `ocr/vlm_tier.py` (quantized local VLM) | **Done, exceeds plan** | `paddle.py` → PaddleOCR-VL through llama.cpp GGUF. The plan proposed `bitsandbytes` 4/8-bit in-process; GGUF via a separate server is a stronger quantization story and keeps VRAM off the API process. |
| `ocr/router.py` (3-way tier decision) | **Partial — biggest OCR gap** | See §2. |
| `reconstruction/markdown_builder.py` | **Partial** | `normalizer/` reconstructs Markdown and parses HTML tables with row/colspan handling. There is no dedicated table-structure recovery beyond what the engine emits. |

### Extraction & validation — built

| Plan component | Status | Notes |
|---|---|---|
| `extraction/extractor.py` | **Done** | `llm_extraction.py`, OpenAI structured outputs with a strict JSON schema. |
| `extraction/schemas.py` (Pydantic model + reconciliation validator) | **Done** | `core/domain/purchase_order.py`. The domain is Purchase Orders, not the plan's invoices, so the invariant is `quantity × unit_price ≈ extension` rather than `subtotal + tax = total`. Required adding an `extension` field — the old schema captured quantity and unit_price but no line total, so nothing could be cross-checked. |
| `validation/business_rules.py` | **Done** | Date format and plausibility, duplicate item codes, zero-priced lines. Error/warning severities: only errors consume a retry. |
| `validation/self_heal.py` (targeted retry loop) | **Done** | Feeds back the exact failing field and figures. Retries run inside the same LLM slot, so they cost latency rather than concurrency. |

The plan asks for the JSON schema and the validator to be "one model doing double
duty"; that is what `PurchaseOrder` is — `EXTRACTION_JSON_SCHEMA` is generated
from it, so the shape the model is constrained to and the shape that is validated
cannot drift apart.

Two deliberate divergences from the plan:

- **Tolerance is relative, not the plan's flat `0.01`.** Line totals on these
  documents run to seven figures, and a unit price printed to two decimals can
  legitimately leave the product a few units off. A relative tolerance absorbs
  that while still catching the real failure mode, an OCR column shift, which is
  wrong by orders of magnitude.
- **Exhausted retries return `200` with `validation.status = "needs_review"`,
  not an error.** The plan routes these to a `needs_review` queue; there is no
  queue yet, so the signal is surfaced in the response and the caller decides.

### Infrastructure & operations — absent

| Plan component | Status | Notes |
|---|---|---|
| Postgres + schema (`documents`, `extraction_jobs`, `extracted_records`, `review_actions`) | **Missing** | No database. Results are written to `outputs/<stem>/<stem>.{md,json}`. |
| `queue/tasks.py` + `worker.py` (procrastinate) | **Missing** | Processing is synchronous within the request. |
| `POST /documents` → job id, `GET /documents/{id}` | *Diverged* | Actual: `POST /v1/extract/local`, `POST /v1/extract/online`, `POST /v1/doc/ocr`, `GET /healthz`. Caller blocks for the full pipeline. |
| `review_app/streamlit_review.py` (HITL) | **Missing** | No `needs_review` state to review. |
| `eval/run_eval.py` | **Done** | One command; reports field accuracy, % requiring review, self-heal recovery rate, and per-field accuracy. `--fail-under` makes it a CI gate. |
| Labeled set (20–30 real documents) | **Missing — now the binding constraint** | The shipped `synthetic.json` is 12 hand-written cases. It exercises the validation layer honestly but says nothing about OCR accuracy. See §6. |
| `.github/workflows/ci.yml` | **Done** | Suite on Python 3.11, then `run_eval --fail-under 0.92` as an accuracy gate, then `compileall` + `pyflakes`. Installs `requirements-ci.txt`, since the full file needs CUDA and a custom index. |
| `tests/` | **Done** | 140 tests. `tests/` was git-ignored; that is now lifted. The plan names `test_business_rules.py` and `test_self_heal.py` specifically — both exist. `test_router.py` does not, because routing is out of scope (§2). |
| `/metrics` + Prometheus/Grafana *(extended scope)* | **Missing** | `GET /healthz` now reports live per-stage occupancy, which is a partial substitute. |
| ONNX INT8 quantization *(extended scope)* | **Partial** | The fast tier already runs through ONNX Runtime, but there is no explicit INT8 quantization step and no before/after latency/memory numbers. |

---

## 2. The routing gap

The plan calls `ocr/router.py` "the centerpiece feature": route each document by
measured quality — text layer → fast OCR → VLM — deciding per document.

What exists is two separate, coarser decisions:

- `ParseOrchestrator` routes by **file type**: `.docx`→Word, `.xlsx`→Excel,
  `.pdf` with a usable text layer→native, everything else→OCR.
- `LocalOCRSelector` picks VLM-vs-fast by **hardware**, once at startup: GPU
  present → PaddleOCR-VL for everything; CPU only → PaddleOCR v6 for everything.

So on a GPU box every scan goes to the VLM, including clean single-column ones a
fast tier would handle in a fraction of the time; on a CPU box every scan goes to
the fast tier, including messy multi-column forms it will read badly. The
per-document quality decision the plan describes is not made anywhere.

Closing this needs `quality_score.py` plus a real `router.py`, and the fast tier
must be loadable alongside the VL tier rather than instead of it.

**Decided 2026-08-01: keep the either/or selection.** Loading both tiers on a GPU
box was declined, which makes per-document routing impossible by construction —
the fast tier is not in memory to route to. The plan's "centerpiece" is therefore
deliberately out of scope, not merely unbuilt. Reopening it means reopening that
decision first. The cost is that clean single-column scans still go to the VLM on
a GPU box, and messy multi-column forms still go to the fast tier on a CPU box.

---

## 3. Rough effort

Estimates assume one developer familiar with this codebase, and include tests.
They are planning-grade, not commitments.

| Work | Effort | Depends on | Value |
|---|---|---|---|
| ~~Pydantic extraction schema + reconciliation validator~~ | **done** | — | Built. |
| ~~`validation/business_rules.py`~~ | **done** | — | Built. |
| ~~`validation/self_heal.py` retry loop~~ | **done** | — | Built. Retries are bounded by `LLM_SELF_HEAL_MAX_RETRIES` and share one LLM slot. |
| Postgres + schema + migrations | 1 day | — | Medium. Prerequisite for everything below. |
| procrastinate queue + worker; `POST /documents` → job id, `GET /documents/{id}` | 2–3 days | Postgres | Medium-high. Decouples client timeouts from OCR time and survives restarts. Note the current bounded-concurrency design already handles multi-request load *within* one process; the queue adds durability, not throughput. |
| `needs_review` status wiring + `review_actions` | 0.5 day | queue | Medium |
| Streamlit review app | 1–2 days | queue | Medium |
| ~~`eval/run_eval.py`~~ | **done** | — | Built. Runs in one command; scores replayed or live extractions. |
| ~~CI workflow + test suite~~ | **done** | — | Built. 140 tests, plus an accuracy gate and lint. |
| Labeled set: 20–30 real documents + ground truth | 1–1.5 days | real documents (you hold these) | **Highest.** The harness exists and is idle. Nothing else here can be shown to have helped until this lands. |
| `quality_score.py` + real 3-way `router.py` | 2 days | both tiers loadable together — **declined**, see §2 | Out of scope by decision |
| `image_prep.py` (deskew/binarize/denoise) | 1 day | labeled set | Medium. Only pays off on genuinely poor scans; measure before adopting. |
| `/metrics` + Prometheus/Grafana | 1–2 days | — | Low until there is production traffic |
| ONNX INT8 quantization + benchmark | 1–2 days | — | Low |

---

## 4. Suggested sequencing

1. ~~**Validation first**~~ — done.
2. ~~**Eval harness**~~ — done. The runner, metrics and report exist and are
   verified; only the data is missing.
3. ~~**Tests + CI**~~ — done. 140 tests and an accuracy gate, so everything
   below has a regression net under it before it is built.
4. **Label 20–30 real documents** (~1–1.5 days) — now the top item, and the only
   one that needs something the repo cannot produce for itself. Every number
   below is unmeasurable until this exists, and it settles both open questions
   in §5. Confirmed 2026-08-01 that the documents exist but stay on your side,
   so this is a task for you to run, not for the repo to acquire — see §7.
5. **Persistence + queue + `needs_review`** (~3.5–4.5 days) once there is a
   meaningful "this one failed validation" state worth storing and reviewing.
   The `needs_review` status already exists in the response; it just has nowhere
   durable to live.
6. **Review app** (~1–2 days).
7. Extended scope (metrics, quantization) last. ~~Router~~ is out of scope by
   the §2 decision.

---

## 5. Decisions this raises

1. **Is the synchronous API a problem in practice?** After the concurrency work,
   one process handles concurrent uploads with bounded stages and sheds load
   cleanly. A queue adds durability across restarts and frees callers from
   holding a connection for minutes — but it is ~3–4 days and adds a database to
   operate. Worth it only if documents are large/slow or uploads are bursty.
2. ~~**Invoice or Purchase Order?**~~ Settled: Purchase Order, with an added
   `extension` field so `quantity × unit_price` has something to reconcile
   against.
3. ~~**Should the fast tier be available on GPU machines?**~~ Settled: no. See
   §2 — this closes out per-document routing as well.
4. **Is `PO_LINE_TOTAL_TOLERANCE_RATIO = 0.01` right?** Still open, and still set
   blind. Too tight and clean extractions burn retries; too loose and a genuine
   misread slips through. The harness can now settle this in one run against
   real documents — sweep the ratio and watch where `needs_review` starts firing
   on documents that are actually fine. It cannot be settled against synthetic
   fixtures, because the fixtures were written to whatever the current threshold
   is.
5. ~~**Do any real documents omit line totals entirely?**~~ Settled 2026-08-01:
   line totals are printed on nearly every document. So the reconciliation check
   runs on nearly every line and earns its place, and question 4 above matters
   more rather than less. The `null-extension-unverifiable` blind spot stays
   real but rare — worth keeping in the eval set so a shift in document format
   shows up as a measurable change rather than a silent one.

---

## 6. What the harness already shows

Against the 12 synthetic cases — **fixtures, not documents**, so read these as
properties of the validation layer and not as pipeline accuracy:

```text
Field accuracy       93.0%  (120/129 fields)
Exact record match   66.7%  (8/12 cases)
Requiring review      8.3%  (1/12 cases)
Recovery rate        75.0%  (3 of 4 first-attempt failures corrected)
```

The one number here that is genuinely informative is the **three validation
blind spots** — cases that satisfy every deterministic check and are still
wrong. They are not fixture artifacts; they are structural:

| Case | What happens | Why no check can catch it |
|---|---|---|
| `dropped-line-item` | A row is missed entirely; 70.6% accurate, reported valid | Every row that *was* returned reconciles |
| `consistent-but-wrong` | Quantity misread, line total computed from it; 71.4% accurate, reported valid | The arithmetic agrees with itself |
| `null-extension-unverifiable` | Quantity misread on a document with no line totals; 91.7% accurate, reported valid | A null `extension` leaves nothing to reconcile against |

This is the honest limit of deterministic validation, and it is the argument for
the labeled set rather than for more rules. The reconciliation check catches
column shifts well; it cannot catch a plausible misreading, and it cannot notice
something that is not there. Only ground truth can.

It also explains a design choice worth keeping: the prompt tells the model to
copy the line total **as printed** rather than compute it. A model that computes
turns every quantity misread into `consistent-but-wrong` — silently valid, and
undetectable without ground truth.

---

## 7. The labeled set is yours to build

Confirmed 2026-08-01: the documents exist but stay on your side. So this is the
one remaining task the repository cannot do for itself, and everything in §4
below step 4 waits on it. It is roughly a day's work.

1. Put 20–30 documents in `eval/labeled_set/documents/`.
2. Write `eval/labeled_set/real.json`, one case per document, with the expected
   record. The format is in `eval/labeled_set/README.md`; `synthetic.json` is a
   worked example.
3. Run `python -m eval.run_eval --source local --json outputs/eval.json`.

Three things worth doing deliberately:

- **Label from the document, not from a pipeline run.** Ground truth taken from
  output measures self-consistency, not accuracy, and will look excellent while
  telling you nothing.
- **Bias the selection toward what fails today.** Clean single-column scans are
  already near 100%; they add cost and no information. Pick the layouts you know
  cause trouble — multi-column, stamped, skewed, multi-page tables.
- **Include a few documents whose stated totals genuinely do not reconcile**, if
  such documents exist. The loader warns rather than fails on those, and they
  set the ceiling on the achievable validity rate. Better to know that ceiling
  than to mistake it for a bug.

The first real run answers question 4 in §5 — sweep
`PO_LINE_TOTAL_TOLERANCE_RATIO` and watch where `needs_review` starts firing on
documents that are actually fine. Neither the synthetic set nor any amount of
reasoning can settle that; only the documents can.

Once `real.json` exists, raise the `--fail-under` threshold in
`.github/workflows/ci.yml` from 0.92 to whatever the real set scores, less a
point or two of headroom. At that point CI is measuring the pipeline rather than
the fixtures, which is the whole objective.
