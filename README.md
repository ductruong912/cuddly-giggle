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
- **Auto-artifacts** — saves every result as a `.md` file under `outputs/`.
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
├── scripts/                      # setup_llama_cpp, preflight_runtime, eval helpers
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

---

## Configuration

All configuration lives in the **`.env`** file (loaded automatically on startup).
Edit `.env` to change behavior — there is no need to export shell variables.

Most-used settings:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | API server binding. |
| `OCR_PRIMARY_ENGINE` | `paddleocr_vl` | Primary engine (`paddleocr_vl` or `pp_structure_v3`). |
| `OCR_FALLBACK_ENGINE` | `pp_structure_v3` | Used only if the primary OCR engine fails. |
| `OCR_DEVICE` | `gpu:0` | GPU selector for the OCR engines (e.g. `gpu:0`). |
| `WARMUP_MODELS_ON_STARTUP` | `true` | Load OCR models into GPU memory at boot (faster first request). |
| `PADDLEOCR_VL_USE_GGUF` | `false` | `true` runs PaddleOCR-VL recognition via llama.cpp + GGUF. |
| `PADDLE_PDX_CACHE_HOME` | `.paddlex` | Where downloaded OCR models are cached. |
| `PARSE_OUTPUT_DIR` | `outputs` | Where parsed `.md` files are saved. |
| `TABLE_ONLY_OUTPUT` | `false` | Keep only tables in the Markdown output. |
| `PDF_TEXT_PARSE_ENABLED` | `true` | Use the native PDF text fast-path before OCR. |

GGUF / llama.cpp settings (used only when `PADDLEOCR_VL_USE_GGUF=true`):

| Variable | Default | Description |
| :--- | :--- | :--- |
| `LLAMA_SERVER_AUTOSTART` | `true` | Auto-start `llama-server` from `main.py` (Windows). |
| `LLAMA_SERVER_HOST` / `LLAMA_SERVER_PORT` | `127.0.0.1` / `8080` | llama.cpp server binding. |
| `LLAMA_SERVER_N_GPU_LAYERS` | `40` | Layers offloaded to GPU. Lower this on small-VRAM cards. |
| `LLAMA_CPP_DIR` / `LLAMA_CPP_MODELS_DIR` | `llama` / `models` | Local folders for binaries and GGUF models. |
| `LLAMA_CPP_RELEASE_FLAVOR` | `win-cuda-12.4-x64` | llama.cpp Windows release flavor to download (e.g. `win-cuda-13.3-x64` for CUDA 13). |
| `LLAMA_CPP_RELEASE_URL` | *(empty)* | Pin a specific llama.cpp release zip; empty = latest GitHub release. |

See `.env.example` for the complete list (rasterization, native-text thresholds,
confidence heuristics, logging, etc.).

---

## Running the Service

After editing `.env`, start the server:

- Windows (PowerShell): `venv\Scripts\python.exe main.py`
- Linux/macOS: `venv/bin/python main.py`

On first start the app downloads the required OCR models into `.paddlex/official_models`
and warms them up on the GPU. Then open the interactive docs:

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

Run `main.py`. It downloads any missing `llama/` binaries and `models/` GGUF files,
starts `llama-server.exe`, points PaddleOCR-VL at `http://127.0.0.1:8080/v1`, then
starts the API. To pre-download the artifacts beforehand:

```bash
venv\Scripts\python.exe scripts\setup_llama_cpp.py
```

### 4. Linux

Scenarios 1 and 2 work as-is (use `venv/bin/python main.py`). The **automatic**
GGUF bootstrap targets Windows binaries, so on Linux run your own OpenAI-compatible
llama.cpp server and disable autostart in `.env`:

```dotenv
PADDLEOCR_VL_USE_GGUF=true
LLAMA_SERVER_AUTOSTART=false
PADDLEOCR_VL_REC_SERVER_URL=http://127.0.0.1:8080/v1
```

### 5. Offline / air-gapped

1. On an internet-connected machine, run the service once so models are cached under `.paddlex/official_models` (and, for GGUF, run `scripts/setup_llama_cpp.py`).
2. Copy the project together with the `.paddlex/` folder (and `llama/` + `models/` if using GGUF) to the offline host.
3. If you store the cache elsewhere, point to it in `.env`:

```dotenv
PADDLE_PDX_CACHE_HOME=D:/deploy/.paddlex
```

> Do not commit `.paddlex/`, `outputs/`, `llama/`, or `models/` — they are git-ignored on purpose.

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

Saved artifacts use the uploaded filename stem (e.g. `VB 6.pdf` → `VB 6.md`);
duplicate names become `VB 6 (2).md`, `VB 6 (3).md`, and so on.

**Example (cURL)**

```bash
curl -X POST \
  'http://127.0.0.1:8000/v1/doc/parse' \
  -H 'accept: text/markdown' \
  -H 'Content-Type: multipart/form-data' \
  -F 'file=@sample_invoice.pdf;type=application/pdf'
```

### `GET /healthz`

Liveness probe. Returns `{"status": "ok"}`.

---

## Testing & Diagnostics

Check system readiness (Python, GPU, Paddle, model cache):

```bash
venv\Scripts\python.exe scripts\preflight_runtime.py
```

Run the test suite:

```bash
venv\Scripts\python.exe -m pytest -q
```

(On Linux use `venv/bin/python` in place of `venv\Scripts\python.exe`.)

---

## License

See [LICENSE](LICENSE).
