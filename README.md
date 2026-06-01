# Cuddly Giggle: Vietnamese Document OCR & Extraction API 

A production-ready, self-hosted API backend designed for high-precision parsing of Vietnamese documents, scanned images, and PDFs. It intelligently combines native PDF text extraction, Vision-Language (VL) OCR models, and structural document parsing to deliver accurate JSON and Markdown outputs.

## Key Features

- **Smart PDF Parsing**: Instantly extracts native text layer using PyMuPDF. Bypasses heavy OCR when high-quality digital text is available.
- **Legacy Font Repair**: Auto-detects and converts legacy Vietnamese printer fonts (TCVN3 / VNI / ABC) to standard Unicode.
- **Vision-Language OCR**: Leverages **PaddleOCR-VL** (v1.6) as the primary engine for complex layouts and robust Vietnamese OCR.
- **Resilient Fallback**: Automatically cascades to **PP-StructureV3** for highly-structured outputs if the primary engine yields borderline confidence or low image quality.
- **Auto-Artifacts**: Automatically saves parse results as `JSON` and/or `Markdown` to your local `outputs/` directory.
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

---

## Configuration

The app uses a `.env` file for configuration. Copy `.env.example` to `.env` (if available) or create one. Environment variables can also be set directly in your terminal.

| Variable | Default | Description |
| :--- | :--- | :--- |
| `OCR_PRIMARY_ENGINE` | `paddleocr_vl` | Primary extraction engine (`paddleocr_vl` or `pp_structure_v3`). |
| `OCR_FALLBACK_ENGINE` | `pp_structure_v3` | Secondary engine if the primary fails quality/confidence thresholds. |
| `PADDLEOCR_VL_PIPELINE_VERSION`| `v1.6` | Specific version of the VL pipeline to download/use. |
| `WARMUP_MODELS_ON_STARTUP` | `true` | Load models into GPU RAM during server boot (reduces latency of first request). |
| `OCR_DEVICE` | `gpu:0` | Hardware selector (`gpu:0`, `cpu`, etc.). |
| `PARSE_OUTPUT_DIR` | `outputs` | Directory to save `.md` and `.json` files. |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Uvicorn server binding. |

---

## Running the Service

Start the backend server. The first startup will download required AI models into `.paddlex/official_models` and warm them up on the GPU.

```powershell
$env:OCR_DEVICE="gpu:0"
venv\Scripts\python.exe main.py
```

> **API Interactive Docs**: Visit http://127.0.0.1:8000/docs once the server is running to view the Swagger UI.

---

## API Usage

### `POST /v1/doc/parse`

Extracts content from an uploaded document (PDF, PNG, JPG).

**Form-Data Parameters:**
- `file`*(required)*: The document binary.
- `lang_hint`*(optional)*: Language hint (`auto` or `vi`).
- `output_format` *(optional)*: Which artifact to save and return (`json`, `markdown`, `both`). Default is `json`.
- `enable_fallback` *(optional)*: Set to `true`/`false`. Defauts to application settings.
- `output_basename` *(optional)*: Custom prefix for saved files in the `outputs/` folder.

**Example via cURL:**
```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/v1/doc/parse' \
  -H 'accept: application/json' \
  -H 'Content-Type: multipart/form-data' \
  -F 'file=@sample_invoice.pdf;type=application/pdf' \
  -F 'output_format=both'
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

## Testing & Diagnostics

**Check System Readiness (Python, GPU, Paddle, Model Cache):**
```powershell
venv\Scripts\python.exe scripts\preflight_runtime.py
```

**Run Unit Tests:**
```powershell
venv\Scripts\python.exe -m pytest -q
```