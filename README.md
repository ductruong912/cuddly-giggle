# Cuddly Giggle

FastAPI service for extracting Vietnamese documents into Markdown or structured JSON. It supports PDFs, Word and Excel files, and common image formats.

## Highlights

- Uses native text extraction for digital PDF, DOCX, XLSX, and XLSM files.
- Uses PaddleOCR-VL for scans and complex layouts.
- Provides a faster CPU OCR route for PDF and image files.
- Saves generated Markdown and extraction artifacts in `outputs/`.

## Requirements

- Python 3.9–3.11
- NVIDIA GPU and CUDA for PaddleOCR-VL OCR
- Optional: LibreOffice for legacy `.doc` and `.xls` files

Native text extraction and the fast CPU OCR route can run without a GPU.

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

Edit `.env` to select the OCR device and, if needed, add `OPENAI_API_KEY` for structured extraction.

Choose one OCR setup that matches the machine before starting the service.
`requirements.txt` contains packages shared by every profile; install the
PaddlePaddle runtime separately so its CPU or CUDA build matches the host.

```bash
# CPU-only: fast ONNX OCR models (no PaddlePaddle installation required)
python scripts/setup_models.py --fast-onnx

# Native NVIDIA GPU: full PaddleOCR stack (recommended when VRAM is sufficient)
python -m pip install "paddlepaddle-gpu==3.3.0" -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
python scripts/setup_models.py --paddleocr-vl
```

For a low-VRAM NVIDIA GPU, use the GGUF + llama.cpp backend instead. It still
needs the PaddlePaddle CUDA wheel for detection and layout processing:

```bash
python -m pip install "paddlepaddle-gpu==3.3.0" -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
python scripts/setup_runtime.py --llama
```

The CUDA 12.6 index must match the installed CUDA-compatible PaddlePaddle wheel;
use the appropriate Paddle package index for another CUDA version.

On Windows, `python scripts/setup_runtime.py --check` checks runtime readiness.

## Run

```bash
python main.py
```

Open [Swagger UI](http://127.0.0.1:8000/docs). The health endpoint is available at `GET /healthz`.

## Main API routes

| Route | Description |
| --- | --- |
| `POST /v1/extract/local` | Local OCR plus structured extraction. Automatically uses PaddleOCR-VL on GPU and PaddleOCR v6 on CPU. |
| `POST /v1/extract/online` | DataLab SuryaOCR plus structured extraction for PDFs and images. |
| `POST /v1/doc/ocr` | Local OCR only; returns Markdown for debugging and does not call the LLM. |
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
