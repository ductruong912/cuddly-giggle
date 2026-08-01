# Cuddly Giggle

FastAPI service for extracting Vietnamese documents into Markdown or structured JSON. It supports PDFs, Word and Excel files, and common image formats.

## Highlights

- Uses native text extraction for digital PDF, DOCX, XLSX, and XLSM files.
- `POST /v1/extract/local` chooses PaddleOCR-VL + GGUF/llama.cpp on NVIDIA GPU, or PaddleOCR v6 on CPU.
- `POST /v1/extract/online` sends PDFs and images to DataLab SuryaOCR.
- Saves generated Markdown and extraction artifacts in `outputs/`.

## Requirements

- Python 3.10+ (3.11 is what the Docker image ships)
- NVIDIA GPU is optional; it enables the local PaddleOCR-VL + GGUF/llama.cpp path.
- Optional: LibreOffice for legacy `.doc` and `.xls` files

## How It Works

For each uploaded file the orchestrator picks the cheapest reliable path:

```
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
│   ├── domain/schemas.py          # Pydantic models
│   ├── engines/
│   │   ├── base.py                # Engine interface
│   │   ├── registry.py            # Config-driven engine factory (used by scripts)
│   │   ├── native.py              # PDF / Word / Excel text-layer parsers
│   │   ├── paddle.py              # PaddleOCR-VL adapter
│   │   ├── paddle_fast.py         # PaddleOCR v6 CPU adapter
│   │   ├── fast_datalab.py        # DataLab SuryaOCR adapter
│   │   └── normalizer.py          # Normalizes engine output to the page schema
│   └── prompts/prompt.py          # Extraction instructions + JSON schema
├── services/
│   ├── document_extraction.py     # parse → extract → save pipeline
│   ├── concurrency.py             # Stage limiters + worker-pool sizing
│   ├── orchestrator.py            # Per-file-type engine selection
│   ├── online_orchestrator.py     # DataLab parse path
│   ├── llm_extraction.py          # OpenAI structured-output adapter
│   ├── local_ocr_selector.py      # GPU/CPU engine choice
│   ├── vl_runtime.py              # llama.cpp lifecycle
│   ├── llama.py                   # llama.cpp bootstrap + server control
│   ├── model_assets.py            # Model-profile manifest checks
│   └── output.py                  # Markdown table filter + artifact writing
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
python scripts/setup_models.py --fast-onnx
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
python scripts/setup_models.py --paddleocr-vl
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

### Online OCR: DataLab SuryaOCR

`POST /v1/extract/online` does not require local OCR models, llama.cpp, or a GPU. Configure only the DataLab credential:

```dotenv
DATALAB_API_KEY=your_datalab_api_key_here
FAST_OCR_DATALAB_MODE=balanced
```

- API: <http://localhost:8000> (Swagger at `/docs`)
- llama (debug only): <http://localhost:8080>

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

## API routes

| Route | Description |
| --- | --- |
| `POST /v1/extract/local` | Local OCR plus structured extraction. Uses PaddleOCR-VL on GPU and PaddleOCR v6 on CPU. |
| `POST /v1/extract/online` | DataLab SuryaOCR plus structured extraction for PDFs and images. |
| `POST /v1/doc/ocr` | Auxiliary local OCR-only debugging endpoint; returns Markdown and does not call the LLM. |
| `GET /healthz` | Liveness check plus live per-stage occupancy. |

Use `multipart/form-data` with a `file` field. The local route supports PDF,
DOC/DOCX, XLS/XLSX/XLSM, PNG, JPG, BMP, WEBP, TIFF, and Markdown; it also accepts
already-parsed Markdown as a `text/markdown`, `text/plain`, or
`application/json` (`{"markdown": "..."}`) body. The online route supports PDFs
and images only.

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

## Docker

The Docker stack runs the API and a CUDA-enabled llama.cpp server:

```bash
docker compose up --build
```

It requires Docker with NVIDIA GPU support. Place GGUF models in `models/`; Paddle model cache is stored in `.paddlex/`.

## Tests

There is no automated suite in the repository yet (`tests/` is git-ignored).
`pytest` is pinned in `requirements.txt` so one can be added without a
dependency change.

## License

See [LICENSE](LICENSE).
