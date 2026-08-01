# Project 2 — Agent Prompts (Hybrid Document Processing Pipeline)

**How to use this file:** copy one step's block at a time into your coding agent (Claude Code, Cursor, etc.), working inside the `doc-pipeline` repo. Let it finish and check the acceptance criteria before moving to the next step. Each prompt only assumes what earlier steps built — the agent can read the actual repo for anything it needs beyond what's stated here.

Steps 0–17 are the base 4-week build. Steps 18–19 are the Extended Scope additions (ONNX quantization, observability) — only needed if you're building those.

---

### Step 0 — Project setup (Day 1)

```
I'm building a document-processing/OCR pipeline backend in Python 3.11+ using FastAPI. Set up the initial repository skeleton with this exact structure:

cuddly-giggle/
├── docker-compose.yml
├── .env.example
├── pyproject.toml
├── README.md
├── app/
│   ├── main.py
│   ├── config.py
│   ├── api/
│   ├── preprocessing/
│   ├── ocr/
│   ├── reconstruction/
│   ├── extraction/
│   ├── validation/
│   ├── queue/
│   ├── db/
│   │   └── migrations/
│   ├── quantization/
│   ├── observability/
│   └── eval/
│       └── labeled_set/
├── review_app/
├── monitoring/
├── tests/
└── .github/workflows/ci.yml

Requirements:
1. docker-compose.yml with a `postgres` service (image postgres:16, db=docpipeline, user=docpipe, password=docpipepass, port 5433:5432) and an `app` service (build from local Dockerfile, port 8001:8000, GPU reservation via nvidia driver).
2. .env.example with: DATABASE_URL, LLM_PROVIDER, LLM_API_KEY, LLM_MODEL_EXTRACT, VLM_MODEL_PATH, VLM_QUANTIZATION, FAST_OCR_ENGINE, STORAGE_PATH.
3. app/config.py using pydantic-settings.
4. pyproject.toml with dependencies: fastapi, uvicorn[standard], pydantic, pydantic-settings, opencv-python, pymupdf, pdf2image, paddleocr, transformers, torch, accelerate, bitsandbytes, procrastinate[psycopg], sqlalchemy, psycopg[binary], streamlit, structlog, pytest, pytest-asyncio.
5. app/main.py with a GET /health endpoint.
6. Create the migration file app/db/migrations/0001_init.sql with exactly these four tables:

CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE extraction_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id),
    status TEXT NOT NULL CHECK (status IN ('pending','processing','needs_review','completed','failed')),
    ocr_tier_used TEXT,
    retry_count INT NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE extracted_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES extraction_jobs(id),
    schema_version TEXT NOT NULL,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE review_actions (
    id BIGSERIAL PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES extraction_jobs(id),
    reviewer TEXT,
    action TEXT NOT NULL CHECK (action IN ('approved','edited','rejected')),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_jobs_status ON extraction_jobs(status);

7. .github/workflows/ci.yml running lint + pytest on push.

Acceptance criteria: `docker-compose up` starts postgres cleanly and applies the migration; /health returns 200. Do not build any OCR, extraction, or queue logic yet.
```

---

### Step 1 — Tier 0 text-layer check + preprocessing (Day 2)

```
Continuing doc-pipeline. Repo skeleton and DB schema exist.

Build app/preprocessing/text_layer.py:

import fitz  # PyMuPDF

def has_text_layer(pdf_path: str, min_chars: int = 50) -> bool:
    doc = fitz.open(pdf_path)
    total_chars = sum(len(page.get_text().strip()) for page in doc)
    return total_chars >= min_chars

Build app/preprocessing/image_prep.py with a preprocess(image: np.ndarray) -> np.ndarray function using OpenCV: convert to grayscale, deskew (via minAreaRect on thresholded pixel coordinates and an affine warp), adaptive-threshold binarize, and denoise (fastNlMeansDenoising).

Acceptance criteria: test has_text_layer() against one digital (text-based) PDF and one scanned image saved as PDF — confirm it correctly returns True/False respectively. Test preprocess() visually on a skewed/noisy sample scan and confirm the output is straightened and cleaner. Do not build any OCR calls yet.
```

---

### Step 2 — Fast OCR tier (Day 3)

```
Continuing doc-pipeline. text_layer.py and image_prep.py exist.

Build app/ocr/fast_tier.py: a function run_fast_ocr(image: np.ndarray) -> dict using PaddleOCR (or pytesseract if FAST_OCR_ENGINE=tesseract in config), returning {"text": str, "avg_confidence": float, "word_boxes": [...]}. Preprocess the image with app/preprocessing/image_prep.preprocess() before running OCR.

Acceptance criteria: running run_fast_ocr() on a clean sample scan returns reasonably accurate text with a high avg_confidence (>0.85), and on a deliberately blurry/noisy sample returns a lower avg_confidence. Do not build the VLM tier or router yet.
```

---

### Step 3 — Quality score + first-pass router (Day 4)

```
Continuing doc-pipeline. run_fast_ocr() exists and returns text + avg_confidence.

Build app/preprocessing/quality_score.py: a function quality_score(image, fast_ocr_result) -> dict returning {"simple_layout": bool, "score": float}, using simple heuristics (e.g. estimated column count via horizontal projection profile, whitespace ratio, avg_confidence from the OCR result).

Build a first-pass app/ocr/router.py:

def route_document(doc_path: str) -> str:
    if has_text_layer(doc_path):
        return "tier0_direct_extract"
    image = load_page_image(doc_path)
    prepped = preprocess(image)
    fast_result = run_fast_ocr(prepped)
    quality = quality_score(prepped, fast_result)
    if quality["simple_layout"] and fast_result["avg_confidence"] > 0.85:
        return "tier2_fast_ocr"
    return "tier1_vlm"  # stub this branch to just return a placeholder for now

Acceptance criteria: route_document() correctly returns "tier0_direct_extract" for a digital PDF and "tier2_fast_ocr" for a clean scan. The "tier1_vlm" branch can just log "not yet implemented" for now. Do not build the VLM tier itself yet — that's next.
```

---

### Step 4 — Upload endpoint, synchronous, fast-tier path only (Day 5)

```
Continuing doc-pipeline. route_document() works for tier0 and tier2 paths.

Build app/api/routes_upload.py: a POST /documents endpoint accepting a multipart file upload. For now, process it synchronously (no queue yet):
1. Save the file to STORAGE_PATH, insert a row into `documents`.
2. Call route_document() to decide the path.
3. For tier0: extract text directly via PyMuPDF. For tier2: run the fast OCR pipeline. (tier1/VLM path can return a "not yet implemented" error for now.)
4. Insert a row into `extraction_jobs` with the resulting status and ocr_tier_used, and return the job id + extracted raw text in the response.

Wire this router into app/main.py.

Acceptance criteria: uploading a digital PDF and a clean scanned image via this endpoint (e.g. with curl or httpie) both succeed end-to-end and return extracted text, with the correct ocr_tier_used recorded in the database. Do not build the VLM tier, async queue, or structured extraction yet.
```

---

### Step 5 — VLM tier (Day 6-7)

```
Continuing doc-pipeline. The tier0/tier2 paths work synchronously. VLM_MODEL_PATH and VLM_QUANTIZATION are configured in .env.

Build app/ocr/vlm_tier.py: load a quantized local vision-language OCR model (a small VLM, 2-7B params, e.g. from the Qwen-VL or PaddleOCR-VL family) via transformers + bitsandbytes, using 4-bit or 8-bit quantization per VLM_QUANTIZATION. Expose run_vlm_ocr(image: np.ndarray) -> str that prompts the model to output the document's content as clean Markdown (including tables where present).

Test this specifically on a genuinely messy, multi-column, or low-quality sample document — the case the fast tier struggles with.

Acceptance criteria: run_vlm_ocr() produces materially better structured output than run_fast_ocr() on the same messy sample document, and fits comfortably in your GPU's VRAM. Do not wire this into the router yet — that's the next step.
```

---

### Step 6 — Complete 3-way router (Day 8)

```
Continuing doc-pipeline. run_vlm_ocr() exists and works standalone.

Update app/ocr/router.py to replace the "tier1_vlm" placeholder with a real call to run_vlm_ocr() when quality["simple_layout"] is False or fast_result["avg_confidence"] <= 0.85.

Update routes_upload.py to handle the tier1_vlm case fully (previously it returned "not yet implemented").

Benchmark: process one sample document through each of the three paths and record processing time for each in a simple table (can just be a comment in the code or a short markdown note) — this becomes README material later.

Acceptance criteria: all three routing paths (tier0, tier2, tier1) work end-to-end through POST /documents, with the correct ocr_tier_used recorded for each. Do not build table reconstruction beyond raw text yet — that's next.
```

---

### Step 7 — Markdown/table reconstruction (Day 9-10)

```
Continuing doc-pipeline. All three OCR tiers produce raw text or markdown output.

Build app/reconstruction/markdown_builder.py: a function reconstruct_markdown(ocr_output, tier: str) -> str that:
- For tier1 (VLM): the model's Markdown output is likely already close to correct — do light cleanup (strip extraneous text, normalize heading levels).
- For tier2 (fast OCR): use the word/line bounding boxes from run_fast_ocr() to detect table-like grid structures (rows of aligned bounding boxes) and reconstruct them as Markdown tables; treat everything else as plain paragraphs in reading order (top-to-bottom, left-to-right per detected column).

Wire this into routes_upload.py: store the reconstructed Markdown (not raw OCR text) as the job's intermediate output.

Acceptance criteria: for a sample invoice or document containing a real table, the reconstructed Markdown renders as a properly aligned Markdown table, not a jumbled line of numbers. Do not build structured extraction yet — that's the next step (and the next week's focus).
```

---

### Step 8 — Extraction schema (Day 11)

```
Continuing doc-pipeline. Each processed document now has reconstructed Markdown stored.

Build app/extraction/schemas.py with this exact Pydantic model (adjust field names only if your real document type differs from invoices):

from pydantic import BaseModel, model_validator

class LineItem(BaseModel):
    description: str
    quantity: float
    unit_price: float
    amount: float

class Invoice(BaseModel):
    vendor: str
    invoice_number: str
    invoice_date: str
    line_items: list[LineItem]
    subtotal: float
    tax: float
    total: float

    @model_validator(mode="after")
    def check_math(self):
        computed_subtotal = round(sum(li.amount for li in self.line_items), 2)
        if abs(computed_subtotal - self.subtotal) > 0.01:
            raise ValueError(
                f"subtotal mismatch: line items sum to {computed_subtotal}, "
                f"stated subtotal is {self.subtotal}"
            )
        if abs((self.subtotal + self.tax) - self.total) > 0.01:
            raise ValueError(
                f"total mismatch: subtotal+tax={self.subtotal + self.tax}, "
                f"stated total is {self.total}"
            )
        return self

Write a couple of quick manual tests instantiating this model with correct and deliberately-wrong-math data to confirm the validator fires correctly.

Acceptance criteria: Invoice.model_validate() succeeds on correct data and raises ValidationError with a clear message on data with mismatched sums. Do not build the LLM extraction call yet — that's next.
```

---

### Step 9 — Extractor (Day 12)

```
Continuing doc-pipeline. app/extraction/schemas.py defines Invoice.

Build app/extraction/extractor.py: an async function extract(markdown_text: str) -> dict that calls the cloud LLM (via LLM_MODEL_EXTRACT) using its native structured-output/tool-calling mode, passing Invoice.model_json_schema() as the target schema, and returns the parsed JSON dict (before Pydantic validation — that happens in the next step).

Wire this into routes_upload.py (or a new processing function) so that after markdown reconstruction, extract() is called and the raw dict is attempted against Invoice.model_validate() — for now, on failure just store the error message in extraction_jobs.error_message and set status to "failed" (the self-healing retry comes next).

Acceptance criteria: for a clean, well-formatted sample invoice, extract() + Invoice.model_validate() succeeds end-to-end and the extracted_records table gets a correct row. Do not build the retry/self-heal loop or additional business rules yet.
```

---

### Step 10 — Business rules (Day 13)

```
Continuing doc-pipeline. Basic extraction + the Pydantic math validator work.

Build app/validation/business_rules.py with any reconciliation checks beyond what Invoice.check_math already covers — for example: invoice_date is a plausible, parseable date; invoice_number matches an expected format/pattern if your domain has one; currency/amount formatting is consistent across line items. Keep this to checks that are genuinely deterministic and meaningful for your document type — don't pad this with rules that don't reflect anything real about your data.

Wire validate_business_rules(invoice: Invoice) -> list[str] (returns a list of violation messages, empty if clean) into the extraction flow after Pydantic validation succeeds.

Acceptance criteria: a correctly-parsed invoice with, say, an implausible date or malformed invoice number is now caught by validate_business_rules even though it passed Pydantic validation. Do not build the self-healing retry loop yet — that's next.
```

---

### Step 11 — Self-healing retry (Day 14)

```
Continuing doc-pipeline. Extraction + Pydantic validation + business_rules all exist as separate checks.

Build app/validation/self_heal.py:

async def extract_with_self_heal(markdown_text: str, max_retries: int = 3) -> Invoice | None:
    raw = await extract(markdown_text)
    for attempt in range(max_retries):
        try:
            invoice = Invoice.model_validate(raw)
            violations = validate_business_rules(invoice)
            if not violations:
                return invoice
            raise ValueError(f"business rule violations: {violations}")
        except (ValidationError, ValueError) as e:
            correction_prompt = build_correction_prompt(markdown_text, raw, errors=str(e))
            raw = await extract(correction_prompt)
    return None

Build build_correction_prompt() to include the exact error message(s) so the LLM is told precisely which field(s) to fix, not just "try again."

Replace the direct extract() call in the processing flow with extract_with_self_heal(). If it returns None after max_retries, set extraction_jobs.status = "needs_review".

Acceptance criteria: deliberately feed a document that produces a wrong extraction on the first attempt (or synthetically corrupt the first LLM response in a test) and confirm the retry loop corrects it within max_retries, or correctly falls through to needs_review if it can't. Do not build unit tests or the async queue yet.
```

---

### Step 12 — Unit tests (Day 15)

```
Continuing doc-pipeline. Core extraction + validation + self-heal logic all exist.

Write:
- tests/test_business_rules.py — a correct invoice passes validate_business_rules with no violations; an invoice with a bad date/format is caught.
- tests/test_self_heal.py — using a mocked extract() that returns a broken result on the first call and a correct one on the second, confirm extract_with_self_heal() succeeds within max_retries; using a mock that always fails, confirm it returns None after exactly max_retries attempts.
- tests/test_router.py — using fixture files, confirm route_document() returns "tier0_direct_extract" for a digital PDF, "tier2_fast_ocr" for a clean scan, and "tier1_vlm" for a synthetically messy/low-quality image.

Acceptance criteria: `pytest` passes on all three files without hitting real LLM APIs or GPU models (mock those dependencies). Do not build the async queue yet — that's next week's focus.
```

---

### Step 13 — Async queue (Day 16-17)

```
Continuing doc-pipeline. Processing currently happens synchronously inside the upload request.

Build app/queue/tasks.py using procrastinate (Postgres-backed, no Redis needed):

from procrastinate import App, PsycopgConnector

app = App(connector=PsycopgConnector(conninfo=settings.DATABASE_URL))

@app.task(retry=3)
async def process_document(document_id: str):
    job = create_job(document_id)
    tier = route_document(get_storage_path(document_id))
    markdown = run_ocr_tier(tier, document_id)
    result = await extract_with_self_heal(markdown)
    if result is None:
        mark_needs_review(job.id)
    else:
        save_record(job.id, result)
        mark_completed(job.id)

Build app/queue/worker.py as the worker process entrypoint. Add a `worker` service to docker-compose.yml running `python -m app.queue.worker`.

Update app/api/routes_upload.py: instead of processing synchronously, save the file, insert the documents row, enqueue process_document.defer(document_id=...), and return {"job_id": ...} immediately.

Add GET /documents/{id} returning the current status and result (if completed).

Acceptance criteria: uploading a document returns immediately with a job_id; polling GET /documents/{id} shows status progressing from pending → processing → completed (or needs_review) as the worker picks it up. Do not build the review UI yet.
```

---

### Step 14 — Needs-review wiring (Day 18)

```
Continuing doc-pipeline. Jobs that exhaust self-heal retries are marked needs_review, but there's no way to act on them yet.

Build simple data-access functions in app/db/models.py (or a new app/db/queries.py):
- get_jobs_by_status(status: str)
- get_document_image(document_id: str)
- approve_job(job_id: str, edited_data: dict, reviewer: str) — inserts a review_actions row with action="approved" or "edited", updates the extracted_records row if edited, and sets extraction_jobs.status = "completed".

Acceptance criteria: you can manually call approve_job() (e.g. from a Python shell) on a needs_review job and confirm its status flips to completed and a review_actions row is created. Do not build the Streamlit UI yet — that's next.
```

---

### Step 15 — HITL Streamlit review page (Day 19)

```
Continuing doc-pipeline. get_jobs_by_status(), get_document_image(), and approve_job() exist.

Build review_app/streamlit_review.py:
- A dropdown/selectbox listing all jobs with status="needs_review" (show filename + error_message).
- On selecting one: display the original document image side-by-side with an editable text area containing the last extraction attempt as JSON.
- An "Approve" button that parses the edited JSON and calls approve_job().

Add a `review` service to docker-compose.yml running `streamlit run review_app/streamlit_review.py` on port 8501.

Acceptance criteria: you can open the Streamlit app, see a real needs_review job from your test data, correct the JSON, click Approve, and see the job's status flip to completed in the database. Do not build the eval harness yet.
```

---

### Step 16 — Eval harness (Day 20, part 1)

```
Continuing doc-pipeline. The full pipeline works end-to-end including HITL review.

Label 20-30 of your sample documents with ground-truth extracted fields, stored as JSON files under app/eval/labeled_set/ (one file per document, matching the Invoice schema).

Build app/eval/run_eval.py: for each labeled document, run it through the full pipeline (or just the extraction step if you want faster iteration), compare the extracted result field-by-field against ground truth, and compute:
- field-level accuracy (% of fields matching exactly, or within tolerance for numeric fields)
- % of documents that required self-heal retries
- % of documents that landed in needs_review

Print a summary and save to app/eval/results.json.

Acceptance criteria: running `python -m app.eval.run_eval` produces real field-level accuracy and review-rate numbers against your labeled set. Do not write the README yet — that's next.
```

---

### Step 17 — README (Day 20, part 2)

```
Continuing doc-pipeline. The full base-scope system is built and tested, with real eval numbers in app/eval/results.json.

Write README.md covering:
1. One-paragraph project overview and what it demonstrates.
2. Architecture diagram (ASCII is fine): document → Tier 0 text-layer check → preprocessing → fast OCR / VLM tier (routed) → markdown reconstruction → structured extraction → business validation → self-heal retry → save or needs-review queue → HITL review.
3. Setup instructions (docker-compose up, env vars, how to run the worker, how to open the review app).
4. Your actual eval numbers from app/eval/results.json (field-level accuracy, retry rate, review rate).
5. A "Design Decisions & Trade-offs" section explaining, in your own words: why a Postgres-backed queue instead of Celery/Temporal; why ONNX Runtime instead of TensorRT (note this is planned for Extended Scope if not yet built); why a Streamlit review page instead of a standalone HITL dashboard; why cloud-API structured outputs instead of self-hosted logit-constrained decoding.

Acceptance criteria: a reader with no other context can clone the repo and get it running from the README alone. This closes out the base 4-week build.
```

---

### Step 18 — ONNX quantization (Week 11, Day 1-2) — Extended Scope

```
Continuing doc-pipeline (base build complete). Extending with ONNX Runtime quantization for the fast OCR tier.

Note: Tesseract isn't a neural model and has nothing to export — this step applies to PaddleOCR's detection/recognition networks specifically. If FAST_OCR_ENGINE is currently "tesseract", switch it to "paddleocr" for this step.

Build app/quantization/onnx_export.py:
1. Export PaddleOCR's detection and recognition models to ONNX format.
2. Use onnxruntime.quantization.quantize_dynamic() with QuantType.QInt8 to produce INT8-quantized versions.
3. Write a small benchmark script comparing average inference latency and peak memory usage between the original and quantized models, on the same batch of test images.

Update app/ocr/fast_tier.py to run inference through the quantized ONNX Runtime session instead of the original PaddleOCR model.

Acceptance criteria: the benchmark script produces concrete before/after numbers for latency and memory (record these — they go directly into the README). Confirm output text quality is not meaningfully degraded on your test set after quantization. Do not build observability yet — that's the final step.
```

---

### Step 19 — Observability (Week 11, Day 3-5) — Extended Scope

```
Continuing doc-pipeline. All core + most extended-scope features are built.

Build app/observability/metrics.py using prometheus-fastapi-instrumentator and prometheus_client:
- Histogram: stage duration, labeled by stage (preprocessing, ocr, extraction, validation).
- Counter: ocr_tier_selected_total, labeled by tier (tier0/tier2/tier1).
- Counter: self_heal_retry_total.
- Gauge: needs_review_queue_depth (updated periodically or on each status change).

Wire instrumentation into the processing task in app/queue/tasks.py. Expose GET /metrics.

Add prometheus and grafana services to docker-compose.yml (prometheus on port 9091, grafana on port 3001 — different from Project 1's ports so both can run simultaneously). Provision a Grafana dashboard (JSON in monitoring/grafana/dashboards/) with panels for: OCR tier distribution, stage-level latency, and review-queue depth over time.

Acceptance criteria: processing a batch of test documents and then opening Grafana shows live data in at least 3 panels, including a visible OCR tier distribution.
```
