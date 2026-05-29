# Vietnamese Document OCR & Extraction API

Self-host backend de parse PDF scan / anh tai lieu. He thong uu tien PaddleOCR-VL, mac dinh pipeline `v1.6`, co fallback PP-StructureV3, va auto-save ket qua ra `outputs/`.

## Project Structure

```text
main.py                       # root entrypoint: python main.py
app/
  application.py              # FastAPI app factory
  api/
    dependencies.py           # dependency injection
    routes/
      documents.py            # POST /v1/doc/parse
      health.py               # GET /healthz
  core/
    config.py                 # env settings, model cache, GPU bootstrap
  domain/
    schemas.py                # API/domain schemas
  services/
    artifacts.py              # save JSON/Markdown outputs
    orchestrator.py           # primary/fallback/quality flow
    merge.py                  # merge primary + fallback result
    quality.py                # document quality checks
    engines/                  # PaddleOCR-VL, PP-StructureV3 adapters
  eval/
    metrics.py                # CER/WER/table/reading-order metrics
scripts/
  preflight_runtime.py        # check Python/GPU/Paddle/model cache
  evaluate_acceptance.py      # evaluate prediction vs ground truth
tests/                        # unit/regression tests
outputs/                      # auto-saved parse artifacts
data_test/                    # local sample documents
```

## Install

```powershell
python -m venv venv
venv\Scripts\activate
python -m pip install -r requirements-gpu-cu130.txt
```

`requirements.txt` contains common app/OCR packages. `requirements-gpu-cu130.txt` adds the required Paddle GPU runtime for Windows + NVIDIA CUDA 13.

```powershell
python -m pip uninstall -y paddlepaddle
python -m pip install -r requirements-gpu-cu130.txt
```

## Run Backend

Create a local `.env` from `.env.example` if you want file-based configuration. The app loads `.env` automatically and real process env vars keep priority.

By default, `python main.py` initializes PaddleOCR-VL before starting Uvicorn. On a fresh cache this downloads the configured model weights, using `PADDLEOCR_VL_PIPELINE_VERSION` (`v1.6` by default). Set `WARMUP_MODELS_ON_STARTUP=false` to defer model download until the first parse request.

```powershell
$env:OCR_DEVICE="gpu:0"
$env:PARSE_OUTPUT_DIR="outputs"
venv\Scripts\python.exe main.py
```

Optional PaddleOCR-VL version override:

```powershell
$env:PADDLEOCR_VL_PIPELINE_VERSION="v1.6"
```

Set it to an empty string only if you want PaddleOCR to use its package default.

Optional:

```powershell
$env:HOST="127.0.0.1"
$env:PORT="8000"
venv\Scripts\python.exe main.py
```

API docs: `http://127.0.0.1:8000/docs`

## GitHub / Clone Notes

Do not commit model cache or local data:

- `.paddlex/` is PaddleX/PaddleOCR model cache and can be very large.
- `outputs/` contains local parse results.
- `data_test/` contains local/private test documents.
- `venv/` is the local Python environment.

These folders are ignored by `.gitignore`.

After cloning on another machine:

```powershell
git clone <your-repo-url>
cd <your-repo>
python -m venv venv
venv\Scripts\activate
python -m pip install -r requirements-gpu-cu130.txt
$env:OCR_DEVICE="gpu:0"
venv\Scripts\python.exe main.py
```

On the first parse request, PaddleOCR/PaddleX will download model files again into `.paddlex/official_models`.

For offline deployment, copy the old `.paddlex/official_models` folder to the new machine, or mount it as a persistent volume, then set:

```powershell
$env:PADDLE_PDX_CACHE_HOME="C:\path\to\.paddlex"
```

Production recommendation: keep code in GitHub, keep models in a model cache volume/artifact storage, not inside Git.

## API

`POST /v1/doc/parse`

Form fields:

- `file`: PDF/image
- `lang_hint`: `auto` or `vi`
- `output_format`: `json`, `markdown`, `both`
- `enable_fallback`: `true` or `false`
- `output_basename`: optional output filename prefix

Auto-save:

- `json` saves `.json`
- `markdown` saves `.md`
- `both` saves `.json` and `.md`

Response always includes `saved_files[]`.

## Check Runtime

```powershell
venv\Scripts\python.exe scripts\preflight_runtime.py
```

## Test

```powershell
venv\Scripts\python.exe -m pytest -q
```

## Notes

- Model cache defaults to `.paddlex/official_models`.
- First request can be slow because OCR models are loaded into GPU.
- `paddleocr` is the OCR framework package. GPU/CPU is decided by Paddle runtime; production should install `paddlepaddle-gpu` via `requirements-gpu-cu130.txt`.
- PaddleOCR-VL pipeline version defaults to `v1.6` through `PADDLEOCR_VL_PIPELINE_VERSION`.
- If PP-StructureV3 fallback fails, the API still returns PaddleOCR-VL result when primary parsing succeeds.
