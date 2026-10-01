# Cuddly Giggle

A FastAPI service for reading Vietnamese documents, recognizing text (OCR),
and extracting **purchase orders (POs)** into JSON. It supports PDF, Word,
Excel, and image files through HTTP endpoints or Swagger UI at `/docs`.

## Features

- Read Word, Excel, and PDFs with usable text layers directly.
- Run local OCR with PaddleOCR-VL + llama.cpp/GGUF when an NVIDIA GPU is
  detected, or PaddleOCR v6 through ONNX Runtime when no usable GPU is found.
- Use OpenAI to extract PO numbers, dates, item codes, quantities, unit
  prices, and line totals; validate the result and retry corrections.
- Save Markdown/JSON in `outputs/`; optionally store and query document
  extraction history in PostgreSQL.

## Processing flow

```text
Local:  Word/Excel/text PDF -> native parsing --+
        Scanned PDF/image -> CPU or GPU OCR ----+-> Markdown
                                                     |
                                                     v
                                   OpenAI -> PO JSON -> validation
                                                     |
                                    retry corrections (up to 2 by default)
                                                     |
                                      save results -> return response
```

`POST /v1/doc/ocr` stops at Markdown without calling OpenAI. You can also
send existing Markdown to `/v1/extract/local` to skip document parsing.

**Local refers to parsing/OCR:** `/v1/extract/local` still sends Markdown to
OpenAI.

## Prerequisites

| Component | Requirement |
| --- | --- |
| Operating system | Windows 10/11 or 64-bit Linux. The local GPU setup below targets Windows; use Docker GPU on Linux. |
| Python | **3.11**, the version used by this repo's CI and Docker image, with `pip` and `venv`. |
| Git | Required to clone the repository. |
| OpenAI API key | Required for `/v1/extract/local`; unnecessary for `/v1/doc/ocr` alone. |
| NVIDIA GPU | Required only for GPU OCR. Drivers and CUDA libraries must match PaddlePaddle and llama.cpp. The installation example uses Paddle CUDA 12.6. |
| LibreOffice | Required only for legacy `.doc`/`.xls` files, with `soffice` on `PATH`. Included in the Docker image. |
| PostgreSQL | Optional for extraction history. Compose uses PostgreSQL 16. |
| Docker | Required only for Compose: Docker Engine/Desktop, Compose v2, and NVIDIA GPU support. Linux requires NVIDIA Container Toolkit. |

Internet access is needed to install dependencies, download models, and call
external APIs. Local OCR dependencies and models can consume several GB;
allow enough disk space for the virtual environment and model cache.

## Local installation

### 1. Clone and create the environment

```bash
git clone https://github.com/ductruong912/cuddly-giggle.git
cd cuddly-giggle
```

**Windows PowerShell:**

```powershell
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

**Linux:**

```bash
python3.11 -m venv venv
source venv/bin/activate
cp .env.example .env
```

Run subsequent commands from the repository root with the environment active:

```bash
python --version
python -m pip install --upgrade pip
```

Open `.env` and set `OPENAI_API_KEY` if you need PO extraction.

`requirements.txt` contains all application and test dependencies, grouped by
function. Choose the CPU/GPU installation recipe below; both use this same file
and install the matching Paddle wheel separately.
Update the existing values in `.env` for your chosen recipe.

### 2A. Local CPU OCR — no usable GPU

Install the CPU runtime profile:

If Paddle GPU is already installed, uninstall `paddlepaddle-gpu` first to avoid
keeping both Paddle packages in the same environment.

```bash
python -m pip install "paddlepaddle==3.3.0" -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
python -m pip install -r requirements.txt
```

Update `.env` before downloading models:

```dotenv
OCR_DEVICE=cpu
FAST_OCR_DEVICE=cpu
FAST_OCR_INFERENCE_ENGINE=onnxruntime
PADDLEOCR_VL_USE_GGUF=false
LLAMA_SERVER_AUTOSTART=false
```

```bash
python scripts/setup_models.py --auto
```

`--auto` uses the same hardware check as the API. The command downloads models
and writes a manifest into `.paddlex/`; keep both the cache and manifest.
No llama.cpp/GGUF is needed. The API selects its
engine based on hardware; `FAST_OCR_DEVICE=cpu` does not force the CPU path
on a machine with a detected GPU.

### 2B. Local GPU OCR — Windows + PaddleOCR-VL/GGUF

In the virtual environment, install Paddle CUDA before the full dependencies.
If Paddle CPU is installed, uninstall `paddlepaddle` first to avoid keeping
both CPU and GPU packages.

```bash
nvidia-smi
python -m pip install "paddlepaddle-gpu==3.3.0" -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
python -m pip install -r requirements.txt
```

Update `.env`:

```dotenv
OCR_DEVICE=gpu:0
PADDLEOCR_VL_USE_GGUF=true
PADDLEOCR_VL_REC_BACKEND=llama-cpp-server
PADDLEOCR_VL_REC_SERVER_URL=http://127.0.0.1:8080/v1
LLAMA_SERVER_AUTOSTART=true
```

Download the runtime, GGUF files, and OCR models, then check the setup:

```bash
python scripts/setup_runtime.py --llama
python scripts/setup_models.py --auto
python -c "import paddle; print(paddle.device.is_compiled_with_cuda()); print(paddle.device.cuda.device_count())"
python scripts/setup_runtime.py --check
```

The Paddle check must print `True` and a GPU count greater than `0`.
`setup_runtime.py` supports Windows only; it downloads binaries into `llama/`
and GGUF files into `models/`. `setup_runtime.py --ocr-models` delegates to
`setup_models.py --auto`,
and `--dependencies` installs the matching Paddle wheel, then `requirements.txt`.
The script uses the official CPU index or CUDA 12.6 index. For other CUDA builds,
use the manual installation commands with the matching official wheel index.
`--all` skips llama.cpp on CPU machines. `--check` requires local llama assets
only when GPU GGUF autostart is configured.

The API starts llama-server on port `8080` when a local route is first called.

See the Paddle installation guides for
[Windows](https://www.paddlepaddle.org.cn/documentation/docs/install/pip/windows-pip_en.html)
and [Linux](https://www.paddlepaddle.org.cn/documentation/docs/en/install/pip/linux-pip_en.html).
The repo pins GPU version `3.3.0`; Python 3.11 Windows/Linux wheels are in the
[CUDA 12.6 index](https://www.paddlepaddle.org.cn/packages/stable/cu126/paddlepaddle-gpu/).

### 3. Start and check the server

```bash
python main.py
```

Or run the same app through Uvicorn:

```bash
python -m uvicorn api.application:app --host 127.0.0.1 --port 8000
```

The default API address is `http://127.0.0.1:8000`. Keep **one worker** for
GPU use. Set `HOST`/`PORT` in `.env` when starting through `main.py`.

- [Swagger UI](http://127.0.0.1:8000/docs): select an endpoint, choose
  **Try it out**, select a file, and click **Execute**.
- [Health](http://127.0.0.1:8000/healthz): check that the process is serving.
- [Readiness](http://127.0.0.1:8000/readyz): check readiness to serve requests.
  A missing OpenAI key returns `503` even when the OCR-only route is usable.

## Run with Docker GPU

Compose runs **three services: app, llama.cpp, and PostgreSQL**. After cloning,
copy `.env.example` to `.env` and set the OpenAI API key. A Docker-only setup does
not require Python on the host.

1. Download two files from
   [PaddleOCR-VL-1.6-GGUF](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF/tree/main)
   into `models/`: `PaddleOCR-VL-1.6-GGUF.gguf` and
   `PaddleOCR-VL-1.6-GGUF-mmproj.gguf`.
2. Create `.paddlex/` and `outputs/`. On Linux, grant the container user
   **UID 10001** write access: run `mkdir -p .paddlex outputs`, then
   `sudo chown 10001:10001 .paddlex outputs`. On Windows, use
   `New-Item -ItemType Directory -Force .paddlex, outputs` in PowerShell.
3. Build the image, start the backends, and prepare the OCR cache/manifest
   inside the container:

```bash
docker compose build app
docker compose up -d postgres llama
docker compose run --rm --no-deps app python scripts/setup_models.py --paddleocr-vl
docker compose up -d app
docker compose logs -f app
```

Wait for llama to become healthy before preparing the models; check with
`docker compose ps`. Open `/docs` on port `8000`. Compose enables PostgreSQL
history automatically; the database port is `5433` from the host and `5432`
inside the container network. Compose passes only the variables declared in
[docker-compose.yml](docker-compose.yml), rather than all `.env` settings.

## API usage

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/doc/ocr` | Upload a local document and return Markdown without calling the LLM. |
| `POST /v1/extract/local` | Local document or Markdown → PO JSON. |
| `GET /v1/extractions` | List history; filter by `po_number`, `status`, or `toto_number`, and paginate with `limit`/`offset`. |
| `GET /v1/extractions/{request_id}` | Retrieve a stored extraction. |
| `GET /healthz`, `GET /readyz` | Process health and service readiness. |

Upload using `multipart/form-data` with a **`file`** field. Local routes
support PDF, DOC/DOCX, XLS/XLSX/XLSM, and PNG/JPG/JPEG/BMP/WEBP/TIF/TIFF.
The local extraction route also accepts `.md`/`.markdown` files,
`text/markdown` or `text/plain` bodies, and JSON `{"markdown": "..."}`.

Try your own PO file (use `curl.exe` instead of `curl` in Windows PowerShell):

```bash
curl -X POST http://127.0.0.1:8000/v1/extract/local -F "file=@/path/to/po.pdf"
```

Responses contain `request_id`, `ocr` metadata, `data` (`po_number`,
`po_date` in `DD-MM-YYYY` format, and `items`), and `validation`.
A `needs_review` status means the result still needs checking after correction
attempts; the API returns the data. Validation checks the PO number/date,
line items, and quantity × unit price against the stated line total, if present.

Document uploads save Markdown/JSON in `outputs/`. Artifacts are removed
after **14 days** by default; set `PARSE_OUTPUT_RETENTION_DAYS=0` to keep them
indefinitely. Markdown requests are not stored in PostgreSQL history;
Markdown file uploads save only the JSON artifact.

### Enable PostgreSQL history locally (optional)

```bash
docker compose up -d postgres
```

Set this URL in `.env` if using the default Compose credentials, then restart
the API:

```dotenv
DATABASE_URL=postgresql://docpipe:docpipepass@127.0.0.1:5433/docpipeline
```

The schema is created/updated at startup. Leave `DATABASE_URL` empty for
file-only storage. With the database enabled, failed database writes fail
requests by default (`DATABASE_PERSISTENCE_REQUIRED=true`).

## Troubleshooting

| Symptom | Action |
| --- | --- |
| PowerShell blocks `Activate.ps1` | Use `.\venv\Scripts\python.exe` instead of `python`; activation is unnecessary. |
| Missing model profile | Rerun `setup_models.py --fast-onnx` or `--paddleocr-vl` for your engine, keeping the `.paddlex/` cache. |
| GPU/llama does not start | Check drivers, the Paddle CUDA build, and runtime; on Windows, run `setup_runtime.py --check`. For insufficient VRAM, lower `LLAMA_SERVER_N_GPU_LAYERS` (local) or `LLAMA_N_GPU_LAYERS` (Compose). |
| `413` | Defaults: 50 MiB per upload and 100 pages for PDFs through OCR. Split files or adjust `MAX_UPLOAD_BYTES`/`PDF_MAX_PAGES`. LLM input is also capped by `LLM_MAX_INPUT_CHARS`. |
| `429` / `503` / `504` | Rate limit exceeded / dependency or queue unavailable / execution timeout. Check logs and `/readyz`. |

See [.env.example](.env.example) for all configuration options.

## Tests

Leave `DATABASE_URL` empty before running tests to avoid using a real database
configured in `.env`.

```bash
python -m pip install -r requirements.txt
python -m pytest
python -m eval.run_eval --fail-under 0.92
```

CI reads the same file and skips the OCR/image groups for mocked tests.

Tests use mocked providers. Default evaluation scores recorded answers against
synthetic data; it does not measure real OCR accuracy. See the
[evaluation dataset guide](eval/labeled_set/README.md).

## License

See [LICENSE](LICENSE).
