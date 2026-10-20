"""One ZeroGPU Space serving the React playground and its OCR API."""
import os
from pathlib import Path

import spaces  # Must initialize ZeroGPU before importing inference frameworks.
import gradio as gr
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from gradio.utils import get_upload_folder

from core.engines.paddle import PaddleOCRVLEngine
from core.engines.preview import capture_preview_context
from services.model_assets import write_model_profile
from services.orchestrator import ParseOrchestrator
from deploy.huggingface.runtime import demo_settings, gpu_duration, ui_config, validate_input

app_settings = demo_settings()
engine = PaddleOCRVLEngine(app_settings)

# Startup is the explicit model preparation step on ephemeral Space storage.
os.environ['CUDDLY_GIGGLE_MODEL_SETUP'] = '1'
try:
    engine.warmup()
    write_model_profile(app_settings, 'gpu')
finally:
    os.environ.pop('CUDDLY_GIGGLE_MODEL_SETUP', None)

parser = ParseOrchestrator(app_settings, primary_engine=engine)
app = gr.Server(title='Cuddly Giggle', docs_url=None, redoc_url=None)
dist = Path(__file__).resolve().parent / 'frontend' / 'dist'
app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='react-assets')


def uploaded_path(file: gr.FileData) -> str:
    """Only accept files uploaded to this Gradio server."""
    try:
        data = gr.FileData.model_validate(file)
        path = Path(data.path).resolve(strict=True)
        if not path.is_relative_to(Path(get_upload_folder()).resolve()) or not path.is_file():
            raise ValueError('Upload the document through this app first.')
        return str(validate_input(str(path)))
    except (ValueError, OSError) as exc:
        raise gr.Error(str(exc)) from exc


def request_duration(file: gr.FileData) -> int:
    return gpu_duration(uploaded_path(file))


@app.api(name='ocr', concurrency_limit=1)
@spaces.GPU(duration=request_duration)
def ocr(file: gr.FileData) -> dict[str, object]:
    path = uploaded_path(file)
    with capture_preview_context(app_settings.ui_preview_max_bytes,
                                 app_settings.ui_preview_max_edge):
        result = parser.parse(path)
    return result.model_dump(mode='json')


@app.api(name='ui_config', queue=False)
def configuration() -> dict[str, object]:
    return ui_config()


@app.get('/', include_in_schema=False)
@app.get('/playground', include_in_schema=False)
def playground() -> FileResponse:
    return FileResponse(dist / 'index.html', headers={'Cache-Control': 'no-cache'})

if __name__ == '__main__':
    app.launch(
        max_file_size=app_settings.max_upload_bytes,
        show_error=True,
        ssr_mode=False,
        mcp_server=False,
    )
