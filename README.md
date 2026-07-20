# Cuddly Giggle — Vietnamese Document OCR & Extraction API

A self-hosted FastAPI backend for high-precision parsing of Vietnamese documents:
scanned images, PDFs, Word, and Excel files. It combines native text extraction,
Vision-Language (VL) OCR, and structural document parsing, and returns clean
**Markdown**.

---

## Key Features

- **Native PDF fast-path** — pulls the existing text layer with PyMuPDF and skips OCR entirely when a PDF already has high-quality digital text.
- **Word & Excel parsing** — converts `.docx`/`.xlsx`/`.xlsm` directly to Markdown; legacy `.doc`/`.xls` are converted first via LibreOffice/soffice when available.
- **Legacy font repair** — auto-detects and converts legacy Vietnamese printer fonts (TCVN3 / ABC) to standard Unicode.
- **Vision-Language OCR** — uses **PaddleOCR-VL** (v1.6) as the primary engine for complex layouts and robust Vietnamese OCR.
- **Resilient fallback** — cascades to **PP-StructureV3** only when the primary OCR engine fails.
- **Optional GGUF backend** — can run PaddleOCR-VL recognition through llama.cpp + GGUF for lower-VRAM GPUs.
- **Auto-artifacts** — saves every result as a `.md` file in a folder named after the uploaded filename.
- **Offline ready** — model cache can be pre-populated for air-gapped deployments.

---

## How It Works

For each uploaded file the orchestrator picks the cheapest reliable path:

```
            ┌─────────────┐
 upload ──▶ │ orchestrator│
            └─────┬───────┘
                  │  .docx/.doc  ──▶ Word text engine ─────┐
                  │  .xlsx/.xls  ──▶ Excel text engine ─────┤
                  │  .pdf (digital text) ──▶ PDF text engine┤──▶ normalizer ──▶ Markdown ──▶ outputs/
                  │  otherwise / sparse text ──▶ PaddleOCR-VL│
                  │       (on failure) ──────▶ PP-StructureV3┘
```

Native engines (PDF/Word/Excel) run on CPU. The OCR engines (PaddleOCR-VL,
PP-StructureV3) require an NVIDIA GPU.

---

## Project Structure

```text
cuddly-giggle/
├── main.py                       # Entrypoint: bootstraps runtime, starts the API
├── requirements.txt              # Python dependencies (incl. PaddlePaddle GPU)
├── .env.example                  # Sample configuration — copy to .env
├── Dockerfile                    # App image (CUDA 12.6 + Python 3.11 + LibreOffice)
├── docker-compose.yml            # Two-container stack: app + llama.cpp server
├── .env.docker.example           # Optional docker compose overrides — copy to .env
├── app/
│   ├── api/
│   │   ├── application.py         # FastAPI app factory (ASGI entrypoint)
│   │   └── routes.py             # Routes (/v1/doc/parse, /healthz) + orchestrator DI
│   ├── core/
│   │   └── config.py             # Settings + environment bootstrap
│   ├── domain/
│   │   └── schemas.py            # Pydantic models
│   ├── services/
│   │   ├── orchestrator.py       # Per-file-type engine selection + fallback
│   │   ├── output.py             # Markdown table filter + artifact writing
│   │   └── llama.py              # llama.cpp bootstrap + server control
│   └── engines/
│       ├── base.py               # Engine interface
│       ├── registry.py           # Config-driven engine factory
│       ├── native.py             # PDF / Word / Excel text-layer parsers
│       ├── paddle.py             # PaddleOCR-VL + PP-StructureV3 adapters
│       └── normalizer.py         # Normalizes engine output to the page schema
├── scripts/                      # Windows manual setup/recovery and runtime diagnostics
│   ├── setup_runtime.py          # Windows recovery entrypoint for dependencies and model downloads
│   ├── setup_llama_cpp.py        # llama.cpp binaries and GGUF model setup
│   └── preflight_runtime.py      # Read-only runtime readiness check
├── tests/                        # pytest suite
├── outputs/                      # Saved .md artifacts (git-ignored)
└── data_test/                    # Local sample documents (git-ignored)
```

---

## Prerequisites

- **OS**: Windows 10/11 or Linux
- **Python**: 3.9 – 3.11
- **GPU**: NVIDIA GPU with CUDA 13.0 or 12.6 — **required** for the OCR engines
- **Optional**: LibreOffice/soffice on `PATH` — only needed to parse legacy `.doc` / `.xls`

> Native PDF/Word/Excel text extraction works without a GPU, but the OCR engines
> (used for scans, images, and image-only PDFs) need CUDA. Running the OCR engines
> on CPU is **not supported**.

---

## Installation

**1. Clone**

```bash
git clone https://github.com/ductruong912/cuddly-giggle
cd cuddly-giggle
```

**2. Create a virtual environment**

```bash
python -m venv venv
```

Activate it:

- Windows (PowerShell): `venv\Scripts\Activate.ps1`
- Linux/macOS: `source venv/bin/activate`

**3. Install dependencies**

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`requirements.txt` already includes PaddlePaddle GPU (`paddlepaddle-gpu==3.3.0`) and
the package indexes for both **CUDA 13.0** and **CUDA 12.6**. To pin a specific CUDA
build, pass it through pip:

```bash
python -m pip install -r requirements.txt --config-settings="--cuda=13.0"   # or 12.6
```

**4. Create your configuration**

Copy the sample and edit values as needed:

- Windows (PowerShell): `Copy-Item .env.example .env`
- Linux/macOS: `cp .env.example .env`

### Model setup (required before running OCR)

The service never downloads models or llama.cpp binaries. Download only the
profile you plan to serve, before starting the API:

```bash
venv\Scripts\python.exe scripts\setup_models.py --fast-onnx
venv\Scripts\python.exe scripts\setup_models.py --paddleocr-vl
venv\Scripts\python.exe scripts\setup_models.py --pp-structure-v3
venv\Scripts\python.exe scripts\setup_runtime.py --llama
```

`--fast-onnx` downloads `PP-OCRv6_medium_det_onnx` and
`PP-OCRv6_small_rec_onnx` for the CPU-oriented `/v1/doc/extract-fast` route.
`--paddleocr-vl` and `--pp-structure-v3` prepare their respective PaddleOCR
pipelines. `--llama` downloads llama.cpp and the two PaddleOCR-VL GGUF files;
it is needed only when `PADDLEOCR_VL_USE_GGUF=true`.

The compatibility setup script can still prepare the configured primary and
fallback OCR pipelines:

```bash
venv\Scripts\python.exe scripts\setup_runtime.py --ocr-models
```

To inspect the current runtime without changing it, use the read-only check mode:

```bash
venv\Scripts\python.exe scripts\setup_runtime.py --check
```

This delegates to `preflight_runtime.py`, which verifies Python, GPU, Paddle,
and the OCR model cache readiness.

---

## Running the Service

After editing `.env`, start the server:

- Windows (PowerShell): `venv\Scripts\python.exe main.py`
- Linux/macOS: `venv/bin/python main.py`

After the required profile has been prepared, start the app. It loads models
only when the corresponding endpoint first needs them; it does not download
missing artifacts. Then open the interactive docs:

> **Swagger UI**: http://127.0.0.1:8000/docs

---

## Running on Different Machines

Behavior is controlled entirely through `.env`. Pick the scenario that matches the host.

### 1. Standard GPU machine (CUDA 13.0) — default

Install `requirements.txt`, then in `.env`:

```dotenv
OCR_DEVICE=gpu:0
PADDLEOCR_VL_USE_GGUF=false
```

Run `main.py`. This uses the full PaddleOCR-VL model directly on the GPU.

### 2. GPU machine with CUDA 12.6

Install with the cu126 build (`--config-settings="--cuda=12.6"`, see
[Installation](#installation)). The `.env` is the same as scenario 1. Nothing else changes.

### 3. Low-VRAM GPU — GGUF backend (Windows)

If the full model does not fit in GPU memory, run recognition through llama.cpp.
In `.env`:

```dotenv
PADDLEOCR_VL_USE_GGUF=true
LLAMA_SERVER_AUTOSTART=true
LLAMA_SERVER_N_GPU_LAYERS=20
```

Run `scripts/setup_runtime.py --llama` first, then `main.py` starts
`llama-server.exe`, points PaddleOCR-VL at `http://127.0.0.1:8080/v1`, then
starts the API. The service will report an error if the required llama.cpp/GGUF
artifacts are absent:

```bash
venv\Scripts\python.exe scripts\setup_llama_cpp.py
```

### 5. Offline / air-gapped

1. On an internet-connected Windows machine, run the service once so models are cached under `.paddlex/official_models`; for GGUF, run `venv\Scripts\python.exe scripts\setup_runtime.py --llama` (or `scripts/setup_llama_cpp.py`).
2. Copy the project together with the `.paddlex/` folder (and `llama/` + `models/` if using GGUF) to the offline host.
3. If you store the cache elsewhere, point to it in `.env`:

```dotenv
PADDLE_PDX_CACHE_HOME=D:/deploy/.paddlex
```

> Do not commit `.paddlex/`, `outputs/`, `llama/`, or `models/` — they are git-ignored on purpose.

---

## Running with Docker

A two-container stack lets another developer run the project without installing Python,
PaddlePaddle, or LibreOffice by hand:

- **`llama`** — a llama.cpp CUDA server running the PaddleOCR-VL recognition GGUF on GPU.
- **`app`** — FastAPI + PaddleOCR-VL detection/layout on GPU, talking to `llama` over HTTP.

Both share the single GPU (fits a 6 GB card, same as the bare-metal GGUF setup).

### Host requirements (once per machine)

- An **NVIDIA GPU** plus a driver new enough for **CUDA 12.6** (≥ 555 Linux / ≥ 560 on
  Windows + WSL2). The host CUDA *toolkit* version is irrelevant — the container ships
  its own. For an older driver capped at CUDA 11.8, see the override below.
- **Docker** + **NVIDIA Container Toolkit** (on Windows: Docker Desktop with the WSL2
  backend and GPU support enabled).
- The git-ignored **`models/`** (`*.gguf`) and ideally **`.paddlex/`** folders copied
  next to `docker-compose.yml`. Without `.paddlex/`, the first boot downloads the
  detection/layout models (needs internet).

### Start

```bash
docker compose up --build
```

- API: http://localhost:8000 (Swagger at `/docs`)
- llama (debug only): http://localhost:8080

### Tuning / overrides

Copy `.env.docker.example` to `.env` only if you need to change a default:

- `LLAMA_N_GPU_LAYERS` — VRAM offload for recognition (20 suits 6 GB; lower if llama OOMs).
- For an **older driver (CUDA 11.8)**, switch the app image build to the cu118 wheel:

  ```dotenv
  CUDA_TAG=11.8.0-cudnn8-runtime-ubuntu22.04
  PADDLE_INDEX=https://www.paddlepaddle.org.cn/packages/stable/cu118/
  ```

The compose stack sets `PADDLEOCR_VL_USE_GGUF=true`, `LLAMA_SERVER_AUTOSTART=false`, and
points the app at `http://llama:8080/v1`, so the app never bootstraps llama itself.

---

## API Usage

### `POST /v1/doc/parse`

Extracts Markdown from an uploaded document (PDF, DOCX, DOC, XLSX, XLSM, XLS, PNG,
JPG, BMP, WEBP, TIF). The response body is `text/markdown`.

`.docx`/`.xlsx`/`.xlsm` are parsed natively. Legacy `.doc`/`.xls` require
LibreOffice/soffice on the server so they can be converted first.

**Form-data parameters**

- `file` *(required)* — the document binary.

The fallback engine (run only if the primary OCR engine fails) is controlled
server-side by `DEFAULT_ENABLE_FALLBACK` (default `true`).

Artifacts are grouped below `PARSE_OUTPUT_DIR` by uploaded filename stem. With
`PARSE_OUTPUT_DIR=outputs/TOTO`, uploading `512.pdf` writes
`outputs/TOTO/512/512.md`. Uploading `512.pdf` again replaces only
`outputs/TOTO/512/`; other filenames' folders are unchanged.

### `GET /healthz`

Liveness probe. Returns `{"status": "ok"}`.

### `POST /v1/llm/extract`

Uploads a document, runs the same internal OCR orchestrator as the parse API,
then returns structured JSON produced by GPT-5 mini. It does not call
`/v1/doc/parse` over HTTP and does not save a Markdown artifact.

The structure under `data` is defined by `app/prompts/prompt.py`; edit that
file to adapt extraction for invoices, forms, contracts, or another document
type.

### `POST /v1/doc/extract-fast`

CPU-oriented extraction for scanned PDF and image uploads (`PNG`, `JPG`, `BMP`,
`WEBP`, `TIF`). It uses `PP-OCRv6_medium_det` with `PP-OCRv6_small_rec` via
the official ONNX Runtime model variants and recognition batch size eight. The
endpoint is intended for faster CPU processing; unlike PaddleOCR-VL it does not
reconstruct document layout, tables, or formulas.

It returns the same JSON schema as `POST /v1/doc/extract`: OCR metadata under
`ocr` and structured LLM output under `data`. On first use, PaddleOCR downloads
the required ONNX models to `PADDLE_PDX_CACHE_HOME`. `onnxruntime` is installed
from `requirements.txt`; install the PaddlePaddle CPU runtime separately only
when using Paddle-backed endpoints or the `paddle_static` fallback.

### `POST /v1/llm/extract-from-ocr`

Gọi riêng lớp LLM để thử prompt trên toàn bộ nội dung Markdown/HTML đã parse.
Endpoint nhận trực tiếp file `.md` hoặc `.markdown`, không chạy OCR.

---

## Testing & Diagnostics

Check system readiness (Python, GPU, Paddle, model cache) without changing
anything:

```bash
venv\Scripts\python.exe scripts\setup_runtime.py --check
```

`setup_runtime.py --check` delegates to the read-only
`preflight_runtime.py`; you can also run that diagnostic directly.

Run the test suite:

```bash
venv\Scripts\python.exe -m pytest -q
```

(On Linux use `venv/bin/python` in place of `venv\Scripts\python.exe`.)

The tests need no GPU, models, or network. Legacy `.doc`/`.xls` and PDF-engine
tests self-skip when LibreOffice or PyMuPDF is absent.

---

## License

See [LICENSE](LICENSE).
