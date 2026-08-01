# Gap Analysis — Implementation Plan vs. Current Code

Written 2026-08-01, against the repo state after the concurrency/production review.
Companion to `project2_ocr_pipeline_implementation_plan.md`.

**Short version:** the OCR half of the plan is built and in places exceeds it. The
*data* half — deterministic validation, persistence, queueing, human review, and
evaluation — does not exist. The single most valuable missing piece is
deterministic business-rule validation, because that is the feature the plan is
organised around and the one thing that currently has no code behind it at all.

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

### Extraction & validation — the core gap

| Plan component | Status | Notes |
|---|---|---|
| `extraction/extractor.py` | **Done** | `llm_extraction.py`, OpenAI structured outputs with a strict JSON schema. |
| `extraction/schemas.py` (Pydantic `Invoice`/`LineItem` + `check_math`) | **Missing** | `core/prompts/prompt.py` holds a hand-written JSON-schema **dict** for a Purchase-Order domain. There is no Pydantic model and no `model_validator`. |
| `validation/business_rules.py` | **Missing** | No deterministic checks exist. |
| `validation/self_heal.py` (targeted retry loop) | **Missing** | Nothing to retry against. |

This is the substantive gap. The plan's arithmetic reconciliation
(`quantity × unit_price ≈ extension`, `subtotal + tax = total`) currently exists
**only as English instructions inside the LLM prompt** — see the "Validation
Rules" and "Output Invariants" sections of `core/prompts/prompt.py`, which ask the
model to check its own arithmetic and "repair it before returning the JSON".

Asking a model to verify its own arithmetic is not verification. A wrong total
that the model is confident about is returned as a success, with no signal to the
caller. The plan's whole argument — deterministic code catches what the model
misses — has no implementation.

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
| Pydantic extraction schema + reconciliation validator | 0.5–1 day | — | **Highest.** Turns the prompt's aspirations into enforced invariants. |
| `validation/business_rules.py` (date sanity, currency consistency) | 0.5 day | schema | High |
| `validation/self_heal.py` retry loop with targeted correction prompts | 1 day | validator | High. Needs a per-request LLM call budget so retries cannot exhaust the LLM stage. |
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

1. **Validation first** (schema → business rules → self-heal, ~2–2.5 days). It is
   the plan's differentiator, needs no infrastructure, and every later stage
   depends on knowing whether an extraction is trustworthy.
2. **Eval harness + labeled set** (~2 days). Do this second, not last: without a
   measurement you cannot tell whether self-heal or a new router helped.
3. **Persistence + queue + `needs_review`** (~3.5–4.5 days) once there is a
   meaningful "this one failed validation" state worth storing and reviewing.
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
2. **Invoice or Purchase Order?** The plan is written around invoices with
   `subtotal + tax = total`. The shipped prompt extracts POs
   (`po_number`, `toto_number`, `customer_number`, `quantity`, `unit_price`) with
   no total field at all, so the plan's specific reconciliation does not apply as
   written. The equivalent PO invariant is `quantity × unit_price ≈ extension`
   where extension is present — but the current schema does not even capture
   extension, so it cannot be checked. Deciding the real domain determines the
   schema.
3. **Should the fast tier be available on GPU machines?** Required for real
   per-document routing; currently the hardware check makes it either/or.
