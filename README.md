# Cuddly Giggle: Vietnamese Document OCR & Extraction API 

A production-ready, self-hosted API backend designed for high-precision parsing of Vietnamese documents, scanned images, PDFs, and Word files. It intelligently combines native text extraction, Vision-Language (VL) OCR models, and structural document parsing to deliver accurate Markdown outputs.

## Key Features

- **Smart PDF Parsing**: Instantly extracts native text layer using PyMuPDF. Bypasses heavy OCR when high-quality digital text is available.
- **Word Parsing**: Extracts `.docx` directly to Markdown and supports legacy `.doc` through LibreOffice/soffice conversion when available.
- **Excel Parsing**: Extracts `.xlsx` / `.xlsm` worksheets to Markdown tables and supports legacy `.xls` through LibreOffice/soffice conversion when available.
- **Legacy Font Repair**: Auto-detects and converts legacy Vietnamese printer fonts (TCVN3 / VNI / ABC) to standard Unicode.
- **Vision-Language OCR**: Leverages **PaddleOCR-VL** (v1.6) as the primary engine for complex layouts and robust Vietnamese OCR.
- **Resilient Fallback**: Automatically cascades to **PP-StructureV3** for highly-structured outputs if the primary engine yields borderline confidence or low image quality.
- **Auto-Artifacts**: Automatically saves parse results as `Markdown` to your local `outputs/` directory.
- **Offline Ready**: Transparent model caching mechanism allows seamless air-gapped deployments.

---

## Prerequisites

- **OS**: Windows or Linux
- **Python**: 3.9 - 3.11
- **Hardware**: NVIDIA GPU is highly recommended (CUDA 13.0 or 12.6 supported).

---

## Installation & Setup

**1. Clone the repository**
```powershell
git clone https://github.com/ductruong912/cuddly-giggle
cd cuddly-giggle
```

**2. Setup Virtual Environment**
```powershell
python -m venv venv
venv\Scripts\activate  # On Linux use: source venv/bin/activate
```

**3. Install Dependencies**

By default, the project is configured for **CUDA 13.0** on Windows:
```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements-gpu-cu130.txt
```
*(Note: If you have an older NVIDIA driver indicating CUDA 12.6, you should install the cu126 PaddlePaddle wheel instead of this requirements file).*

**4. Optional: pre-download llama.cpp and GGUF models**

This prepares the ignored `llama/` and `models/` folders before the first GGUF run. You can skip this step if `PADDLEOCR_VL_USE_GGUF=true`; `main.py` downloads missing artifacts automatically.

```powershell
venv\Scripts\python.exe scripts\setup_llama_cpp.py
```

---

## Configuration

The app uses a `.env` file for configuration. Copy `.env.example` to `.env` (if available) or create one. Environment variables can also be set directly in your terminal.

| Variable | Default | Description |
| :--- | :--- | :--- |
| `OCR_PRIMARY_ENGINE` | `paddleocr_vl` | Primary extraction engine (`paddleocr_vl` or `pp_structure_v3`). |
| `OCR_FALLBACK_ENGINE` | `pp_structure_v3` | Secondary engine if the primary fails quality/confidence thresholds. |
| `PADDLEOCR_VL_PIPELINE_VERSION`| `v1.6` | Specific version of the VL pipeline to download/use. |
| `PADDLEOCR_VL_USE_GGUF` | `false` | `true` runs PaddleOCR-VL recognition through GGUF + llama.cpp; `false` uses the original PaddleOCR-VL model. |
| `LLAMA_CPP_DIR` | `llama` | Local folder for llama.cpp binaries. |
| `LLAMA_CPP_MODELS_DIR` | `models` | Local folder for GGUF model files. |
| `LLAMA_CPP_RELEASE_URL` | *(empty)* | Optional pinned llama.cpp release zip URL. Empty resolves the latest GitHub release for `LLAMA_CPP_RELEASE_FLAVOR`. |
| `LLAMA_CPP_RELEASE_FLAVOR` | `win-cuda-cu13.3-x64` | llama.cpp Windows release flavor (`win-cuda-cu13.3-x64`, `win-cuda-cu12.4-x64`, or `win-x64`). |
| `LLAMA_SERVER_AUTOSTART` | `true` | When GGUF is enabled, start `llama-server.exe` automatically from `main.py`. |
| `LLAMA_SERVER_HOST` / `LLAMA_SERVER_PORT` | `127.0.0.1` / `8080` | llama.cpp server binding used by the app. |
| `LLAMA_SERVER_N_GPU_LAYERS` | `40` | Number of layers to offload to GPU for llama.cpp. |
| `WARMUP_MODELS_ON_STARTUP` | `true` | Load models into GPU RAM during server boot (reduces latency of first request). |
| `OCR_DEVICE` | `gpu:0` | Hardware selector (`gpu:0`, `cpu`, etc.). |
| `PARSE_OUTPUT_DIR` | `outputs` | Directory to save `.md` files. |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Uvicorn server binding. |

---

## Running the Service

Start the backend server. The first startup will download required AI models into `.paddlex/official_models` and warm them up on the GPU.

```powershell
$env:OCR_DEVICE="gpu:0"
venv\Scripts\python.exe main.py
```

To run the GGUF backend, set one flag before the same command:

```powershell
$env:PADDLEOCR_VL_USE_GGUF="true"
venv\Scripts\python.exe main.py
```

When GGUF is enabled, `main.py` downloads missing `llama/` and `models/` artifacts, starts `llama-server.exe`, points PaddleOCR-VL at `http://127.0.0.1:8080/v1`, then starts the API. Set `PADDLEOCR_VL_USE_GGUF=false` to run the original PaddleOCR-VL model without llama.cpp.

> **API Interactive Docs**: Visit http://127.0.0.1:8000/docs once the server is running to view the Swagger UI.

---

## API Usage

### `POST /v1/doc/parse`

Extracts Markdown from an uploaded document (PDF, DOCX, DOC, XLSX, XLSM, XLS, PNG, JPG). The API response body is `text/markdown`; JSON and `both` output modes are not exposed.

`.docx` files are parsed natively. Legacy `.doc` files require LibreOffice/soffice on the server so they can be converted to `.docx` before parsing.
`.xlsx` and `.xlsm` files are parsed natively. Legacy `.xls` files require LibreOffice/soffice so they can be converted to `.xlsx` before parsing.

**Form-Data Parameters:**
- `file`*(required)*: The document binary.
- `lang_hint`*(optional)*: Language hint (`auto` or `vi`).
- `enable_fallback` *(optional)*: Set to `true`/`false`. Defauts to application settings.
- `output_basename` *(optional)*: Custom basename for saved files in the `outputs/` folder. By default, the Markdown artifact matches the uploaded filename stem (for example `VB 6.pdf` -> `VB 6.md`); duplicate names are saved as `VB 6 (2).md`, `VB 6 (3).md`, and so on.

**Example via cURL:**
```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/v1/doc/parse' \
  -H 'accept: text/markdown' \
  -H 'Content-Type: multipart/form-data' \
  -F 'file=@sample_invoice.pdf;type=application/pdf' \
  -F 'enable_fallback=true'
```

---

## Project Structure

```text
├── main.py                       # Root entrypoint
├── app/
│   ├── application.py            # FastAPI app factory
│   ├── api/                      # Routing & DI
│   ├── core/                     # App settings & environment bootstraps
│   ├── domain/                   # Schemas (Pydantic models)
│   ├── eval/                     # CER/WER metrics tracking
│   └── services/                 # Business logic, Quality checks, Merging
│       └── engines/              # Base classes & Adapters (PaddleOCR, StructureV3)
├── scripts/                      # Utility scripts (preflight checks, evaluation)
├── tests/                        # Unit and integration tests
├── outputs/                      # (Git-ignored) Target folder for parsed artifacts
└── data_test/                    # (Git-ignored) Local sample documents
```

---

## Offline & Production Deployment

For environments without internet access (Air-Gapped):

1. **Pre-download Models**: Run the application once on an internet-connected machine. This caches models inside the `.paddlex/official_models` folder.
2. **Transfer**: Copy the code along with the `.paddlex` folder to your offline server.
3. **Configure Volume**: Set the cache location explicitly if you move it:
   ```powershell
   $env:PADDLE_PDX_CACHE_HOME="C:\deploy\.paddlex"
   ```
*Pro Tip: Do not commit the `.paddlex` or `outputs/` directories to source control. They are `.gitignore`d for a reason!*

---

### Remote VL Recognition / GGUF

The normal GGUF path is a single terminal:

```powershell
$env:PADDLEOCR_VL_USE_GGUF="true"
venv\Scripts\python.exe main.py
```

For advanced setups, set `LLAMA_SERVER_AUTOSTART=false` and run a compatible OpenAI-style server yourself. The app will still use the `PADDLEOCR_VL_REC_*` override variables when `PADDLEOCR_VL_USE_GGUF=true`.

---

## Testing & Diagnostics

**Check System Readiness (Python, GPU, Paddle, Model Cache):**
```powershell
venv\Scripts\python.exe scripts\preflight_runtime.py
```

**Run Unit Tests:**
```powershell
venv\Scripts\python.exe -m pytest -q
```
