# Gap Analysis — Implementation Plan vs. Current Code

Written 2026-08-01, against the repo state after the concurrency/production review.
Updated the same day, after the validation layer was built.
Companion to `project2_ocr_pipeline_implementation_plan.md`.

**Short version:** the OCR half of the plan is built and in places exceeds it.
Deterministic validation and self-healing are now built too (§1, "Extraction &
validation"). What remains missing is persistence, queueing, human review, and
evaluation. Of those, the **eval harness** is now the highest-value next step:
without it there is no way to show that self-healing recovers anything, which
the plan's Definition of Done explicitly asks you to report as a number.

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
| `eval/run_eval.py` + labeled set | **Missing** | No accuracy measurement of any kind. |
| `.github/workflows/ci.yml` | **Missing** | No CI. |
| `tests/` | **Missing** | Also git-ignored. |
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
| `quality_score.py` + real 3-way `router.py` | 2 days | both tiers loadable together | Medium-high |
| `image_prep.py` (deskew/binarize/denoise) | 1 day | — | Medium. Only pays off on genuinely poor scans; measure before adopting. |
| Labeled set (20–30 docs) + `eval/run_eval.py` | 2 days | — | High. Without it, none of the above can be shown to have helped. |
| CI workflow + starter test suite | 1 day | — | High |
| `/metrics` + Prometheus/Grafana | 1–2 days | — | Low until there is production traffic |
| ONNX INT8 quantization + benchmark | 1–2 days | — | Low |

---

## 4. Suggested sequencing

1. ~~**Validation first**~~ — done.
2. **Eval harness + labeled set** (~2 days) — now the top item. Self-healing is
   live but its recovery rate is unmeasured, and the plan's Definition of Done
   asks for that number. It also becomes the yardstick for the router work
   below. The `validation` block in each response makes the "% requiring review"
   metric close to free to compute.
3. **Persistence + queue + `needs_review`** (~3.5–4.5 days) once there is a
   meaningful "this one failed validation" state worth storing and reviewing.
   The `needs_review` status already exists in the response; it just has nowhere
   durable to live.
4. **Review app** (~1–2 days).
5. **Router + preprocessing** (~3 days), measured against the eval harness.
6. Extended scope (metrics, quantization) last.

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
3. **Should the fast tier be available on GPU machines?** Required for real
   per-document routing; currently the hardware check makes it either/or.
4. **Is `PO_LINE_TOTAL_TOLERANCE_RATIO = 0.01` right?** Set to 1% without real
   documents to calibrate against. Too tight and clean extractions burn retries;
   too loose and a genuine misread slips through. The eval harness would settle
   it; until then, watch for `validation.status = "needs_review"` on documents
   that are actually fine.
5. **Do any real documents omit line totals entirely?** `extension` is nullable
   and a null skips the arithmetic check, so such documents get structural
   validation only. If that is the common case, the reconciliation buys less
   than it appears to.
