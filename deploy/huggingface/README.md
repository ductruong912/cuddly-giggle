# React OCR demo on one free ZeroGPU Space

One public Hugging Face Space serves the existing React playground at `/` and
its OCR APIs through Gradio Server mode. There is no separate Gradio demo UI
or second public backend Space. React calls the same origin through the Gradio
client; no Hugging Face token is embedded in the browser.

The demo uses PaddleOCR-VL 1.6 with Transformers instead of GGUF/llama.cpp. It
reuses the parser, normalization, native document readers, and bounding boxes.
This profile disables preprocessing and rotation, OpenAI extraction, database
history, and saved output artifacts.

## Prepare and deploy

Use a personal account with verified email, older than 30 days, and a free
ZeroGPU slot. The Hub API makes the final eligibility decision. See the current
[ZeroGPU policy](https://huggingface.co/docs/hub/spaces-zerogpu).

From the repository root, with Node.js 24 and the project Python environment:

```powershell
.\venv\Scripts\hf.exe auth login
.\venv\Scripts\python.exe scripts/deploy_hf_demo.py
```

Enter the write token only in the login terminal. The script creates one new
public Gradio SDK Space, selects free ZeroGPU, verifies its hardware, and
uploads the combined app. It stops if the name exists; use `--name` to choose
another. It never selects paid hardware. HTTP 402 stops publishing before code
upload; check email verification, account age, and free GPU availability.

To prepare a reviewable upload folder without publishing:

```powershell
.\venv\Scripts\python.exe scripts/prepare_hf_demo.py --backend-space YOUR_USERNAME/cuddly-giggle-demo
```

The legacy `--backend-space` argument names the combined Space. Output under
`test/hf-demo-*/space/` contains source packages, deployment files, and the React
build in `frontend/dist/`. Local secrets, uploaded documents, outputs, models,
caches, and Git metadata are excluded. Upload this folder's contents to the
Space root. An interrupted deployment may leave a newly created Space; inspect
it before retrying. Do not upgrade to a paid plan for a zero-cost demo.

## Runtime limits

Uploads are limited to 20 MiB and 3 PDF pages. The server accepts only files
from its Gradio upload directory. Uploaded documents use temporary Space
storage, not durable history. Download results from React.

GPU reservations are 30 seconds per PDF page (up to 90 seconds), or 30 seconds
for another document. Hugging Face may apply a hardware-dependent multiplier.
When the reservation exceeds remaining quota, React displays requested and
remaining seconds and the reset countdown when provided by the platform.

The first startup downloads models. After deployment, verify the React root
and a real OCR request; a successful build alone is insufficient.

## Local mode

The demo sets `VITE_GRADIO_SPACE=self` to call its own origin. With that variable
unset, normal FastAPI transport is active. Local `.env`, Dockerfile, and Docker
Compose configuration are unchanged.

