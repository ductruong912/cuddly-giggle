# Implementation Plan — Project 2: Hybrid Document Processing Pipeline

Companion doc to the portfolio guide. This is the build-it document: repo layout, schemas, infra, module-by-module logic, and a day-by-day task list.

**Assumptions (swap freely):** example domain is invoice/receipt extraction — it's the cleanest illustration of deterministic business-logic validation (sums must reconcile), which is the whole point of this project. Python 3.11+. Postgres doubles as both the data store and the job queue (via `procrastinate`), so there's no separate queue service to run.

---

## 1. Repository Structure

```
cuddly-giggle/
├── docker-compose.yml
├── .env.example
├── pyproject.toml
├── README.md
├── app/
│   ├── main.py
│   ├── config.py
│   ├── api/
│   │   ├── routes_upload.py       # POST /documents
│   │   ├── routes_jobs.py         # GET /documents/{id}
│   │   └── routes_health.py
│   ├── preprocessing/
│   │   ├── text_layer.py          # Tier 0: native text check
│   │   ├── image_prep.py          # OpenCV deskew/binarize/denoise
│   │   └── quality_score.py       # feeds the tier router
│   ├── ocr/
│   │   ├── fast_tier.py           # PaddleOCR (CPU)
│   │   ├── vlm_tier.py            # quantized local VLM (GPU)
│   │   └── router.py              # tier decision logic
│   ├── reconstruction/
│   │   └── markdown_builder.py    # table + layout reconstruction
│   ├── extraction/
│   │   ├── schemas.py             # Pydantic: Invoice, LineItem
│   │   └── extractor.py           # cloud LLM structured output call
│   ├── validation/
│   │   ├── business_rules.py      # deterministic reconciliation
│   │   └── self_heal.py           # validation-error retry loop
│   ├── queue/
│   │   ├── tasks.py               # procrastinate task definitions
│   │   └── worker.py              # worker entrypoint
│   ├── db/
│   │   ├── models.py
│   │   └── migrations/0001_init.sql
│   ├── quantization/               # Extended Scope
│   │   └── onnx_export.py
│   ├── observability/              # Extended Scope
│   │   └── metrics.py
│   └── eval/
│       ├── labeled_set/            # ground-truth JSON per sample doc
│       └── run_eval.py
├── review_app/
│   └── streamlit_review.py         # HITL page
├── monitoring/                     # Extended Scope
│   ├── prometheus.yml
│   └── grafana/dashboards/
├── tests/
│   ├── test_business_rules.py
│   ├── test_self_heal.py
│   └── test_router.py
└── .github/workflows/ci.yml
```

---

## 2. Infrastructure — `docker-compose.yml`

```yaml
version: "3.9"
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: docpipeline
      POSTGRES_USER: docpipe
      POSTGRES_PASSWORD: docpipepass
    ports: ["5433:5432"]              # different port than Project 1 — can run both stacks at once
    volumes: ["pgdata:/var/lib/postgresql/data"]

  app:
    build: .
    env_file: .env
    ports: ["8001:8000"]
    depends_on: [postgres]
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  worker:
    build: .
    command: ["python", "-m", "app.queue.worker"]
    env_file: .env
    depends_on: [postgres]
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  review:
    build: .
    command: ["streamlit", "run", "review_app/streamlit_review.py", "--server.port=8501"]
    ports: ["8501:8501"]
    env_file: .env
    depends_on: [postgres]

  # --- Extended Scope: uncomment for Week 11 ---
  # prometheus:
  #   image: prom/prometheus:latest
  #   volumes: ["./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml"]
  #   ports: ["9091:9090"]              # different port than Project 1's Prometheus
  # grafana:
  #   image: grafana/grafana:latest
  #   ports: ["3001:3000"]
  #   volumes: ["./monitoring/grafana:/etc/grafana/provisioning"]

volumes:
  pgdata:
```

Each project ships its **own** Postgres + (optionally) its own Prometheus/Grafana — same instrumentation pattern in both, but each repo stays independently runnable so a reviewer can clone and demo either one on its own.

### Core dependencies (`pyproject.toml`)

```
fastapi, uvicorn[standard], pydantic, pydantic-settings,
opencv-python, pymupdf, pdf2image,
paddleocr,                                # fast tier
transformers, torch, accelerate, bitsandbytes,   # VLM tier, 4/8-bit quantized
procrastinate[psycopg],                   # Postgres-backed job queue
sqlalchemy, psycopg[binary],
streamlit, structlog,
pytest, pytest-asyncio

# Extended Scope additions:
onnxruntime-gpu, prometheus-fastapi-instrumentator
```

### `.env.example`

```
DATABASE_URL=postgresql://docpipe:docpipepass@localhost:5433/docpipeline
LLM_PROVIDER=openai
LLM_API_KEY=sk-...
LLM_MODEL_EXTRACT=gpt-4o-mini
VLM_MODEL_PATH=./models/qwen2-vl-2b-instruct   # or a PaddleOCR-VL checkpoint
VLM_QUANTIZATION=4bit                          # 4bit | 8bit | none
FAST_OCR_ENGINE=paddleocr                      # paddleocr | tesseract
STORAGE_PATH=./data/documents
```

---

## 3. Data Model

### Postgres schema (`db/migrations/0001_init.sql`)

```sql
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE extraction_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id),
    status TEXT NOT NULL CHECK (status IN
        ('pending','processing','needs_review','completed','failed')),
    ocr_tier_used TEXT,              -- tier0_direct | tier2_fast | tier1_vlm
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
```

### Pydantic extraction schema (`extraction/schemas.py`)

This is the piece that does double duty: schema-constrained extraction *and* deterministic validation, in one model.

```python
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
```

---

## 4. Module-by-Module Logic

### `preprocessing/text_layer.py` — Tier 0

```python
import fitz  # PyMuPDF

def has_text_layer(pdf_path: str, min_chars: int = 50) -> bool:
    doc = fitz.open(pdf_path)
    total_chars = sum(len(page.get_text().strip()) for page in doc)
    return total_chars >= min_chars
```

Cheapest possible win: if this returns `True`, skip OCR entirely and extract text directly.

### `preprocessing/image_prep.py` — OpenCV pipeline

```python
import cv2
import numpy as np

def preprocess(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    deskewed = _deskew(gray)
    binarized = cv2.adaptiveThreshold(
        deskewed, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 31, 15,
    )
    denoised = cv2.fastNlMeansDenoising(binarized)
    return denoised

def _deskew(gray: np.ndarray) -> np.ndarray:
    coords = np.column_stack(np.where(gray < 255))
    angle = cv2.minAreaRect(coords)[-1]
    angle = -(90 + angle) if angle < -45 else -angle
    h, w = gray.shape
    matrix = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    return cv2.warpAffine(gray, matrix, (w, h),
                           flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
```

### `ocr/router.py` — the centerpiece feature

```python
def route_document(doc_path: str) -> str:
    if has_text_layer(doc_path):
        return "tier0_direct_extract"

    image = load_page_image(doc_path)
    prepped = preprocess(image)
    fast_result = run_fast_ocr(prepped)          # PaddleOCR, returns text + confidence
    quality = quality_score(prepped, fast_result)

    if quality.simple_layout and fast_result.avg_confidence > 0.85:
        return "tier2_fast_ocr"
    return "tier1_vlm"
```

`quality_score` is a small heuristic — DPI, whitespace ratio, detected column count from PaddleOCR's layout output. It doesn't need to be sophisticated; it needs to correctly separate "clean single-column scan" from "messy multi-column form."

### `extraction/extractor.py` — schema-constrained extraction via cloud API

```python
async def extract(markdown_text: str) -> dict:
    response = await llm_client.chat.completions.create(
        model=settings.LLM_MODEL_EXTRACT,
        messages=[{"role": "user", "content": build_extraction_prompt(markdown_text)}],
        response_format={"type": "json_schema", "json_schema": Invoice.model_json_schema()},
    )
    return json.loads(response.choices[0].message.content)
```

Using the cloud API's native structured-output/tool-calling mode gets you grammar-constrained extraction without self-hosting logit-bias tooling (Outlines, etc.) — the API enforces the schema shape at the token level on its end.

### `validation/self_heal.py` — retry loop on validation failure

```python
async def extract_with_self_heal(markdown_text: str, max_retries: int = 3) -> Invoice | None:
    raw = await extract(markdown_text)
    for attempt in range(max_retries):
        try:
            return Invoice.model_validate(raw)
        except ValidationError as e:
            correction_prompt = build_correction_prompt(
                markdown_text, raw, errors=e.errors()
            )
            raw = await extract(correction_prompt)
    return None  # exhausted retries → caller marks job needs_review
```

The correction prompt should include the *exact* Pydantic error (field name + message), not just "try again" — that's what makes the retry targeted instead of a blind re-roll.

### `queue/tasks.py` — Postgres-backed async processing

```python
from procrastinate import App, PsycopgConnector

app = App(connector=PsycopgConnector(conninfo=settings.DATABASE_URL))

@app.task(retry=3)
async def process_document(document_id: str):
    job = create_job(document_id)
    tier = route_document(get_storage_path(document_id))
    text_or_markdown = run_ocr_tier(tier, document_id)
    result = await extract_with_self_heal(text_or_markdown)
    if result is None:
        mark_needs_review(job.id)
    else:
        save_record(job.id, result)
        mark_completed(job.id)
```

No Redis, no Celery, no Temporal — one extra table in the Postgres you already run.

### `review_app/streamlit_review.py` — HITL

```python
jobs = get_jobs(status="needs_review")
selected = st.selectbox("Needs review", jobs, format_func=lambda j: j.document_filename)

col1, col2 = st.columns(2)
with col1:
    st.image(get_document_image(selected.document_id))
with col2:
    edited = st.text_area("Extracted JSON (edit as needed)",
                           value=json.dumps(selected.last_attempt, indent=2))
    if st.button("Approve"):
        approve_and_save(selected.id, json.loads(edited))
```

### `quantization/onnx_export.py` — Extended Scope, Week 11

```python
# PaddleOCR's detection/recognition nets are the target here — Tesseract has
# nothing to export, it isn't a neural model.
from onnxruntime.quantization import quantize_dynamic, QuantType

export_paddle_to_onnx(model_dir="./models/paddleocr", output_path="./models/paddleocr.onnx")
quantize_dynamic(
    model_input="./models/paddleocr.onnx",
    model_output="./models/paddleocr.int8.onnx",
    weight_type=QuantType.QInt8,
)
# Then benchmark: avg inference time and peak memory, before vs. after,
# on the same batch of test images. Put both numbers in the README.
```

---

## 5. API Contract

| Endpoint | Method | Request | Response |
|---|---|---|---|
| `/documents` | POST | multipart file upload | `{"job_id": "..."}` — enqueues, returns immediately |
| `/documents/{id}` | GET | — | `{"status", "ocr_tier_used", "result"?, "error"?}` |
| `/health` | GET | — | `{"status": "ok"}` |
| `/metrics` | GET | — | Prometheus exposition format *(Extended Scope)* |
| Streamlit `review_app` | — | reads directly from Postgres | approve/edit UI, no separate API needed |

---

## 6. Day-by-Day Build Order

### Week 4 — Preprocessing + fast path

| Day | Task |
|---|---|
| 1 | Repo scaffold, `docker-compose up` (postgres + app), run migration, CI skeleton |
| 2 | `text_layer.py` (Tier 0) + `image_prep.py`; test against one digital PDF and one scanned image |
| 3 | `fast_tier.py` (PaddleOCR integration) + per-word confidence extraction |
| 4 | `quality_score.py` + a first-pass `router.py` (fast-tier path only, VLM path stubbed) |
| 5 | `/documents` upload endpoint, synchronous processing (no queue yet) to validate the fast-tier path end-to-end |

### Week 5 — VLM tier + reconstruction

| Day | Task |
|---|---|
| 6–7 | `vlm_tier.py`; load a quantized local VLM (4/8-bit via `bitsandbytes`); design the prompt for clean Markdown output; test on a genuinely messy multi-column sample |
| 8 | Complete `router.py` (3-way: skip / fast / VLM); benchmark latency per path on your GPU |
| 9–10 | `reconstruction/markdown_builder.py`; table detection and reconstruction; validate output quality on a handful of real invoices |

### Week 6 — Structured extraction + validation

| Day | Task |
|---|---|
| 11 | `extraction/schemas.py`; define `Invoice`/`LineItem` with the reconciliation validator |
| 12 | `extraction/extractor.py`; wire the cloud LLM's structured-output call |
| 13 | `validation/business_rules.py`; any reconciliation checks beyond what the Pydantic validator covers (date sanity, currency consistency) |
| 14 | `validation/self_heal.py`; retry loop with targeted correction prompts |
| 15 | Unit tests for the validator and self-heal loop; buffer |

### Week 7 — Async queue + HITL + eval

| Day | Task |
|---|---|
| 16–17 | `queue/tasks.py` (procrastinate) + `worker.py`; migrate the upload endpoint from synchronous to enqueue-and-return |
| 18 | `needs_review` status wiring + `review_actions` table |
| 19 | `review_app/streamlit_review.py` |
| 20 | Label 20–30 sample documents with ground truth; `eval/run_eval.py` computing field-level accuracy and % requiring review; README; demo recording |

### Week 11 (shared with Project 1) — Quantization + observability

| Day | Task |
|---|---|
| 1–2 | `quantization/onnx_export.py`; export + INT8-quantize the fast-tier model; swap `fast_tier.py` to run inference through the ONNX Runtime session; benchmark and record before/after latency + memory |
| 3–5 | `observability/metrics.py`; instrument stage-level duration (preprocessing, OCR, extraction), OCR-tier-selected counter, retry counter, review-queue-depth gauge; expose `/metrics`; add Prometheus + Grafana to `docker-compose.yml`; build 3–4 dashboard panels |

---

## 7. Testing Plan

| Target | Test type | What to check |
|---|---|---|
| `business_rules.py` / `Invoice.check_math` | Unit | Correct invoice passes; an invoice with a deliberately wrong subtotal raises `ValidationError` |
| `self_heal.py` | Unit (mocked LLM) | Given a validation error, the correction prompt includes the specific failing field; loop stops at `max_retries` |
| `router.py` | Unit | A digital PDF routes to `tier0_direct_extract`; a clean scan routes to `tier2_fast_ocr`; a synthetically messy image routes to `tier1_vlm` |
| End-to-end | Integration | Upload → process → stored record, using three fixture documents: one digital PDF, one clean scan, one messy scan |
| Whole system | Acceptance | `eval/run_eval.py` field-level accuracy against your labeled set — CI-friendly proxy for "does it still work" |

---

## 8. Definition of Done — Base Build (Week 7 checkpoint)

- [ ] All three routing paths (Tier 0 / fast / VLM) are exercised by at least one real test document each
- [ ] Business-rule validation catches at least one deliberately broken test invoice
- [ ] Self-healing retry loop measurably recovers some fraction of initially-invalid extractions (report the number)
- [ ] Documents that exhaust retries land in the `needs_review` queue and are actionable from the Streamlit page
- [ ] `eval/run_eval.py` runs in one command and reports field-level accuracy + % requiring review
- [ ] README has a Design Decisions & Trade-offs section covering every "cut" item from the portfolio guide

## 9. Definition of Done — Extended Scope (Week 11 checkpoint)

- [ ] ONNX Runtime INT8 quantization is live in the fast tier, with before/after latency and memory numbers in the README
- [ ] Grafana dashboard shows OCR tier distribution, stage-level latency, and review-queue depth during a demo run
