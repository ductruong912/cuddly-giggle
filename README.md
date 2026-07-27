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

The local CPU path and the online DataLab path work without an NVIDIA GPU.

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

The CUDA package index above is for PaddlePaddle CUDA 12.6; choose the matching index for another supported CUDA version.

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
