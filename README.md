# Cuddly Giggle

FastAPI service for extracting Vietnamese documents into Markdown or structured JSON. It supports PDFs, Word and Excel files, and common image formats.

## Highlights

- Uses native text extraction for digital PDF, DOCX, XLSX, and XLSM files.
- `POST /v1/extract/local` chooses PaddleOCR-VL + GGUF/llama.cpp on NVIDIA GPU, or PaddleOCR v6 on CPU.
- Saves generated Markdown and extraction artifacts in `outputs/`.

OCR runs on the local machine. Structured Purchase Order extraction still sends
the OCR Markdown to OpenAI.

## Requirements

- Python 3.10+ (3.11 is what the Docker image ships)
- NVIDIA GPU is optional; it enables the local PaddleOCR-VL + GGUF/llama.cpp path.
- Optional: LibreOffice for legacy `.doc` and `.xls` files

## How It Works

For each uploaded file the orchestrator picks the cheapest reliable path:

```text
            ┌─────────────┐
 upload ──▶ │ orchestrator│
            └─────┬───────┘
                  │  .docx/.doc  ──▶ Word text engine ──────┐
                  │  .xlsx/.xls  ──▶ Excel text engine ─────┤──▶ normalizer ──▶ Markdown ──▶ LLM ──▶ outputs/
                  │  .pdf (digital text) ──▶ PDF text engine┤
                  │  scans / images / sparse text ──▶ OCR ──┘
                  │        GPU ▸ PaddleOCR-VL (GGUF via llama.cpp)
                  │        CPU ▸ PaddleOCR v6 (ONNX Runtime)
```

Native engines (PDF/Word/Excel) run on CPU and need no models. The OCR tier is
chosen once at startup from the detected hardware.

## Concurrency & capacity

The service is a single process that accepts requests concurrently but admits
only a bounded number into each expensive stage:

| Stage | Setting | Default | Why |
| --- | --- | --- | --- |
| OCR | `OCR_MAX_CONCURRENCY` | 2 | One GPU; `llama-server --parallel 1` serialises recognition anyway. |
| LLM | `LLM_MAX_CONCURRENCY` | 8 | Network-bound, so more can be in flight. |
| Disk | derived | ≥4 | Upload staging and artifact writes; short and never blocks OCR. |

All blocking work (OCR, the OpenAI call, file staging) runs in worker threads, so
the event loop stays free — `GET /healthz` answers in milliseconds while the GPU
is saturated, and reports live per-stage occupancy. Requests that cannot get a
slot within `STAGE_QUEUE_TIMEOUT_SECONDS` are rejected with `503` and a
`Retry-After` header rather than queueing without bound.

Uploads over `MAX_UPLOAD_BYTES` (50 MB) and PDFs over `PDF_MAX_PAGES` (100) are
rejected with `413` before they occupy a slot.

Run one worker process per GPU. Adding `--workers` duplicates the model in VRAM.

---

## Project Structure

```text
cuddly-giggle/
├── main.py                        # Entrypoint: starts uvicorn, nothing else
├── requirements.txt               # Python dependencies (incl. PaddlePaddle GPU)
├── requirements-ci.txt            # Test-only subset, installable without CUDA
├── pytest.ini                     # Test discovery and import path
├── .env.example                   # Sample configuration — copy to .env
├── Dockerfile                     # App image (CUDA 12.6 + Python 3.11 + LibreOffice)
├── docker-compose.yml             # Two-container stack: app + llama.cpp server
├── api/
│   ├── application.py             # FastAPI factory + lifespan (ASGI entrypoint)
│   ├── routes.py                  # /v1/extract/*, /v1/doc/ocr, /healthz
│   ├── dependencies.py            # Process-wide singletons (engines, clients, limiters)
│   ├── errors.py                  # Request errors + the one place they map to HTTP
│   ├── uploads.py                 # Body decoding and size-capped upload staging
│   └── rate_limit.py              # slowapi limiter
├── config/
│   ├── config.py                  # Settings + environment bootstrap
│   └── pipeline_logging.py        # Request-scoped log context
├── core/
│   ├── domain/
│   │   ├── schemas.py             # Request/response models
│   │   ├── purchase_order.py      # The extracted record and its invariants
│   │   └── strict_schema.py       # Pydantic model → OpenAI strict JSON Schema
│   ├── engines/
│   │   ├── base.py                # Engine interface
│   │   ├── native/                # PDF / Word / Excel text-layer parsers
│   │   ├── normalizer/            # Normalizes engine output to the page schema
│   │   ├── paddle.py              # PaddleOCR-VL adapter
│   │   ├── paddle_fast.py         # PaddleOCR v6 CPU adapter
│   └── prompts/prompt.py          # Extraction instructions + JSON schema
├── services/
│   ├── document_extraction.py     # parse → extract → save pipeline
│   ├── concurrency.py             # Stage limiters + worker-pool sizing
│   ├── orchestrator.py            # Per-file-type engine selection
│   ├── llm_extraction.py          # OpenAI structured-output adapter
│   ├── validation/                # Deterministic checks + the self-heal retry loop
│   ├── local_ocr_selector.py      # GPU/CPU engine choice
│   ├── vl_runtime.py              # llama.cpp lifecycle
│   ├── llama/                     # llama.cpp bootstrap + server control
│   ├── model_assets.py            # Model-profile manifest checks
│   └── output.py                  # Markdown table filter + artifact writing
├── eval/
│   ├── run_eval.py                # `python -m eval.run_eval` — accuracy report
│   ├── labeled_set/               # Ground truth, one case per document
│   ├── scoring.py                 # Field-level comparison against ground truth
│   ├── report.py                  # Metric aggregation and rendering
│   ├── runner.py                  # Case execution
│   ├── sources.py                 # Replayed answers, or the live pipeline
│   └── wiring.py                  # Live-source construction + VL runtime
├── tests/                         # pytest suite; runs without the OCR extras
├── .github/workflows/ci.yml       # Tests, accuracy gate, compileall, pyflakes
├── scripts/                       # setup_models, setup_runtime, preflight helpers
└── outputs/                       # Saved .md/.json artifacts (git-ignored)
```

---

## Prerequisites

- **OS**: Windows 10/11 or Linux
- **Python**: 3.9 – 3.11
- **GPU**: NVIDIA GPU with CUDA 13.0 or 12.6 — needed only for the PaddleOCR-VL tier
- **Optional**: LibreOffice/soffice on `PATH` — only needed to parse legacy `.doc` / `.xls`

> Native PDF/Word/Excel text extraction needs no models at all. For scans, images
> and image-only PDFs the service picks its OCR tier from the hardware it finds:
> PaddleOCR-VL on CUDA, PaddleOCR v6 through ONNX Runtime on CPU. The CPU tier is
> considerably slower and lower-fidelity, but it is supported — see
> [Local OCR on CPU](#local-ocr-on-cpu).

---

## Installation

```bash
git clone https://github.com/ductruong912/cuddly-giggle.git
cd cuddly-giggle

python -m venv venv
```

Activate the environment:

```powershell
# Windows PowerShell
venv\Scripts\Activate.ps1
```

```bash
# Linux/macOS
source venv/bin/activate
```

Install the shared dependencies and create the local configuration:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

> The install pulls several GB. `pip` unpacks into the system temp directory, so
> if your system drive is short on space, point it elsewhere first:
>
> ```powershell
> $env:TMP = "D:\build\tmp"; $env:TEMP = $env:TMP; $env:PIP_CACHE_DIR = "D:\build\pipcache"
> ```

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

```bash
# Linux/macOS
cp .env.example .env
```

Configure `.env` according to the API flow you will use. `OPENAI_API_KEY` is required only when calling an extraction endpoint that returns structured data.

### Local OCR on CPU

Use this profile when there is no NVIDIA GPU. It runs PaddleOCR v6 and does not need llama.cpp or PaddlePaddle GPU.

```bash
python scripts/setup_models.py --cpu
```

Keep these values in `.env`:

```dotenv
FAST_OCR_DEVICE=cpu
PADDLEOCR_VL_USE_GGUF=false
```

### Local OCR on NVIDIA GPU: PaddleOCR-VL GGUF via llama.cpp

Use this profile for `POST /v1/extract/local` on a GPU machine. The layout/Paddle side needs a CUDA PaddlePaddle build; GGUF inference runs through the local llama.cpp server.

Do not keep both PaddlePaddle CPU and GPU packages in the same virtual environment:

```powershell
python -m pip uninstall -y paddlepaddle paddlepaddle-gpu
python -m pip install "paddlepaddle-gpu==3.3.0" -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
python scripts/setup_models.py --gpu
python scripts/setup_runtime.py --llama
```

Set these values in `.env`:

```dotenv
OCR_DEVICE=gpu:0
PADDLEOCR_VL_USE_GGUF=true
PADDLEOCR_VL_REC_BACKEND=llama-cpp-server
PADDLEOCR_VL_REC_SERVER_URL=http://127.0.0.1:8080/v1
LLAMA_SERVER_AUTOSTART=true
```

Confirm that Paddle can use the GPU before starting the API:

```powershell
python -c "import paddle; print(paddle.device.is_compiled_with_cuda()); print(paddle.device.get_device())"
```

Expected output is `True` and `gpu:0`. If it says GPU is unavailable, PaddlePaddle was installed without CUDA support or with an incompatible build.

The llama.cpp debug server is available at <http://localhost:8080> when running.

### Tuning / overrides

Copy `.env.example` to `.env` only if you need to change a default:

- `LLAMA_N_GPU_LAYERS` — VRAM offload for recognition (20 suits 6 GB; lower if llama OOMs).
- For an **older driver (CUDA 11.8)**, switch the app image build to the cu118 wheel:

  ```dotenv
  CUDA_TAG=11.8.0-cudnn8-runtime-ubuntu22.04
  PADDLE_INDEX=https://www.paddlepaddle.org.cn/packages/stable/cu118/
  ```

On Windows, `python scripts/setup_runtime.py --check` checks runtime readiness.

## Run

```bash
python main.py
```

Or point any ASGI server at the app factory — the lifespan does all the wiring:

```bash
uvicorn api.application:app --host 0.0.0.0 --port 8000
```

Open [Swagger UI](http://127.0.0.1:8000/docs). The health endpoint is `GET /healthz`.
The API listens on <http://localhost:8000> by default; on GPU setups, the local
llama.cpp debug server listens on <http://localhost:8080>.

## API routes

| Route | Description |
| --- | --- |
| `POST /v1/extract/local` | Local OCR plus structured extraction. Uses PaddleOCR-VL on GPU and PaddleOCR v6 on CPU. |
| `POST /v1/doc/ocr` | Auxiliary local OCR-only debugging endpoint; returns Markdown and does not call the LLM. |
| `GET /healthz` | Liveness check plus live per-stage occupancy. |

Use `multipart/form-data` with a `file` field. The local route supports PDF,
DOC/DOCX, XLS/XLSX/XLSM, PNG, JPG, BMP, WEBP, TIFF, and Markdown; it also accepts
already-parsed Markdown as a `text/markdown`, `text/plain`, or
`application/json` (`{"markdown": "..."}`) body.

### Extraction validation

Extraction is not trusted on the model's word. Every extracted record is checked
deterministically before it is returned:

- **Arithmetic** — `quantity × unit_price` must reproduce the line total printed
  on the document, within `PO_LINE_TOTAL_TOLERANCE_RATIO`. The common failure it
  catches is an OCR column shift, which is wrong by orders of magnitude.
- **Structure** — a PO number, a parseable `DD-MM-YYYY` date, at least one line
  item, positive quantities, non-negative prices.
- **Plausibility** — date within a sane window, repeated item codes, zero-priced
  lines. These are reported as warnings and do not fail the record.

When a blocking check fails, the exact field and figures are fed back to the
model and extraction is retried up to `LLM_SELF_HEAL_MAX_RETRIES` times. Retries
happen inside the same LLM slot, so they cost latency, not concurrency.

Every response carries the result:

```json
{
  "request_id": "req_...",
  "ocr": { "decision": "...", "page_count": 2 },
  "data": { "po_number": "215497", "po_date": "05-08-2026", "items": [...] },
  "validation": {
    "status": "valid",
    "attempts": 2,
    "healed": true,
    "issues": []
  }
}
```

`status` is `needs_review` when the record still fails after the retries are
exhausted. The data is returned regardless, so the caller decides whether to
route it to a human — there is no review queue yet.

The extraction JSON Schema is generated from the `PurchaseOrder` model rather
than written by hand, so what the model is constrained to and what is validated
afterwards cannot drift apart. It is checked against OpenAI's strict-mode rules
at import, making a malformed schema a startup error instead of a per-request
400.

### Error responses

| Status | Meaning |
| --- | --- |
| `400` | Missing `file` field, unsupported file type, or an undecodable body. |
| `413` | Upload over `MAX_UPLOAD_BYTES`, PDF over `PDF_MAX_PAGES`, or OCR text over `LLM_MAX_INPUT_CHARS`. |
| `415` | Content-Type the route does not accept. |
| `422` | The model returned output that did not satisfy the extraction schema. |
| `429` | Rate limit (`RATE_LIMIT_DEFAULT` / `RATE_LIMIT_EXTRACT`) exceeded. |
| `503` | A dependency is unavailable, or every slot for a stage stayed busy — retry after `Retry-After`. |
| `504` | A stage exceeded its execution timeout and the work was abandoned. |

## Extraction history (PostgreSQL)

Optional. With `DATABASE_URL` unset the service behaves exactly as before and
writes results to `outputs/` only. Set it and every extraction is also recorded
and queryable:

```bash
docker compose up -d postgres
export DATABASE_URL=postgresql://docpipe:docpipepass@127.0.0.1:5433/docpipeline
```

The schema is applied on startup — numbered SQL files in
[services/persistence/migrations/](services/persistence/migrations/), tracked in
a `schema_migrations` table, under a Postgres advisory lock so two instances
starting together cannot race. No Alembic, and therefore no SQLAlchemy.

Two tables. `extractions` holds the record, the validation verdict and the full
JSONB payload, with `po_number` and `po_date` denormalised for lookup.
`extraction_items` holds the line items relationally, so you can ask which
orders contain a part — with money as `NUMERIC(18,4)`, never floating point.

| Route | Purpose |
| --- | --- |
| `GET /v1/extractions` | List, newest first. Filters: `po_number`, `status`, `toto_number`. Paged with `limit`/`offset`. |
| `GET /v1/extractions/{request_id}` | One extraction with its line items. |

```bash
curl 'localhost:8000/v1/extractions?status=needs_review&limit=20'
curl 'localhost:8000/v1/extractions?toto_number=TX703AR'
```

Re-processing the same `request_id` updates in place rather than duplicating, so
a retry is idempotent.

**A failed write fails the request** (`DATABASE_PERSISTENCE_REQUIRED=true`).
Returning `200` for a result that was never recorded loses data silently, and
the caller can retry a `503`. Set it to `false` for best-effort logging. Startup
also fails on an unreachable database rather than deferring the error to the
first upload.

> Note the interaction with `PARSE_OUTPUT_RETENTION_DAYS`: the file sweep deletes
> artifacts after 14 days by default. Once the database is the system of record
> that is usually what you want, but the Markdown is only kept in `outputs/`
> unless you read it back from the `markdown` column.

## Health and readiness

| Endpoint | Answers | Use it for |
| --- | --- | --- |
| `GET /healthz` | Is the process alive and serving? Always `200`. | Container healthcheck. |
| `GET /readyz` | Can this instance actually do work? `503` when not. | Load balancer / orchestrator routing. |

The split matters. `/healthz` deliberately stays green when a *dependency* is
sick, because a container healthcheck that goes red there would restart the API
in a loop while leaving the real problem — usually llama.cpp — untouched.
`/readyz` is the one that reports a dead VL backend, a missing `OPENAI_API_KEY`,
or a stage running below capacity.

### When a backend wedges

A worker thread cannot be cancelled in Python, so a hung call cannot simply be
dropped. The stage limiter therefore fails the *request* at its execution
timeout but keeps the slot booked until the call actually returns, and reports
the stage as degraded:

```json
{ "status": "not_ready",
  "degraded_stages": ["ocr"],
  "stages": { "ocr": { "in_flight": 1, "max_concurrency": 2, "abandoned": 1 } } }
```

Releasing the slot early would admit more work than there is capacity to run it.
`abandoned` slots come back on their own once the call returns — which for a
wedged llama.cpp means restarting it. A backend that has *died* rather than
wedged is detected and restarted automatically on the next request.

## Docker

The Docker stack runs the API and a CUDA-enabled llama.cpp server:

```bash
docker compose up --build
```

It requires Docker with NVIDIA GPU support. Place GGUF models in `models/`; Paddle model cache is stored in `.paddlex/`.

## Evaluation

```bash
python -m eval.run_eval                                  # replay, no API key needed
python -m eval.run_eval --source local --json outputs/eval.json
python -m eval.run_eval --fail-under 0.95                # exits 1 when accuracy drops
```

Scores extractions against the ground truth in [eval/labeled_set/](eval/labeled_set/)
and reports field-level accuracy, the share of documents needing review, and the
self-healing recovery rate — the fraction of extractions that failed validation
on the first attempt and were correct by the last.

Two kinds of case. A **replay** case supplies recorded model answers and runs
them through the real validation loop, so the retry behaviour can be measured
without an OCR engine, an API key or a document. A **document** case runs the
full local OCR and extraction pipeline against a file on disk. `--source replay`
runs the first kind, while `--source local` runs the second; the report says how
many cases were skipped.

> The shipped `synthetic.json` is **12 hand-written cases, not real documents.**
> It measures the validation layer only. Its accuracy figure is a property of the
> fixtures, not of the pipeline — replace it with real purchase orders before
> reading anything into the number. See
> [eval/labeled_set/README.md](eval/labeled_set/README.md).

The report also counts **validation blind spots**: cases that satisfied every
check and are still wrong. Three failure modes cause them, and no amount of
arithmetic checking will catch any of them:

| Blind spot | Why validation cannot see it |
| --- | --- |
| A line item is dropped entirely | Every row that *was* returned reconciles. |
| Quantity is misread and the line total computed from it | The arithmetic agrees with itself. |
| The document states no line totals | With `extension` null there is nothing to reconcile against. |

Only ground truth catches these, which is the argument for a labeled set.

## Tests

```bash
pytest                              # the whole suite, ~18s
pytest tests/test_self_heal.py      # one module
pytest -k concurrency               # by name
```

140 tests covering the record's invariants, the business rules, the self-heal
retry loop, the strict-schema generation, the PDF text-layer engine, the API's
request guards and stage limiters, and the eval harness itself.

The suite needs no sample documents — the PDF fixtures are generated with
PyMuPDF at test time — and no API key, since every extraction is a stand-in.

**It also runs without the OCR extras installed.** The engines defer their
imports, so `paddlepaddle-gpu`, `paddleocr`, `paddlex` and `onnxruntime` are not
needed to exercise anything above. That is what makes CI possible on an ordinary
runner; see [requirements-ci.txt](requirements-ci.txt). What the suite therefore
does *not* cover is OCR inference itself and the live OpenAI call — both need the
full stack and are exercised by running the service.

> `caplog` does not work on this project's loggers. `configure_app_logging` sets
> `propagate = False` (paddlex installs a root handler, and propagating would
> print every line twice), and `caplog` attaches to the root logger. Use the
> `capture_logs` fixture in [tests/conftest.py](tests/conftest.py) instead.

### CI

[.github/workflows/ci.yml](.github/workflows/ci.yml) runs on every push and pull
request: the suite on Python 3.11, then `run_eval --fail-under 0.92` as an
accuracy gate, then `compileall` and `pyflakes`. The evaluation report is
uploaded as a build artifact.

`requirements-ci.txt` is a subset of `requirements.txt` — the full file needs
CUDA and a custom index. `tests/test_requirements.py` fails the build if the two
files' pins ever drift, so CI cannot quietly start testing different versions
than production runs.

## License

See [LICENSE](LICENSE).
