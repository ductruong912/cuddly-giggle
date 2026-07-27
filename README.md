# Cuddly Giggle

FastAPI service for extracting Vietnamese documents into Markdown or structured JSON. It supports PDFs, Word and Excel files, and common image formats.

## Highlights

- Uses native text extraction for digital PDF, DOCX, XLSX, and XLSM files.
- `POST /v1/extract/local` chooses PaddleOCR-VL + GGUF/llama.cpp on NVIDIA GPU, or PaddleOCR v6 on CPU.
- `POST /v1/extract/online` sends PDFs and images to DataLab SuryaOCR.
- Saves generated Markdown and extraction artifacts in `outputs/`.

## Requirements

- Python 3.9–3.11
- NVIDIA GPU is optional; it enables the local PaddleOCR-VL + GGUF/llama.cpp path.
- Optional: LibreOffice for legacy `.doc` and `.xls` files

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

- API: http://localhost:8000 (Swagger at `/docs`)
- llama (debug only): http://localhost:8080

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

Open [Swagger UI](http://127.0.0.1:8000/docs). The health endpoint is available at `GET /healthz`.

## API routes

| Route | Description |
| --- | --- |
| `POST /v1/extract/local` | Local OCR plus structured extraction. Automatically uses PaddleOCR-VL on GPU and PaddleOCR v6 on CPU. |
| `POST /v1/extract/online` | DataLab SuryaOCR plus structured extraction for PDFs and images. |
| `POST /v1/doc/ocr` | Auxiliary local OCR-only debugging endpoint; returns Markdown and does not call the LLM. |
| `GET /healthz` | Liveness check. |

Use `multipart/form-data` with a `file` field. The local route supports PDF, DOC/DOCX, XLS/XLSX/XLSM, PNG, JPG, BMP, WEBP, and TIFF; the online route supports PDFs and images.

## Docker

The Docker stack runs the API and a CUDA-enabled llama.cpp server:

```bash
docker compose up --build
```

It requires Docker with NVIDIA GPU support. Place GGUF models in `models/`; Paddle model cache is stored in `.paddlex/`.

## Tests

```bash
python -m pytest -q
```

## License

See [LICENSE](LICENSE).
