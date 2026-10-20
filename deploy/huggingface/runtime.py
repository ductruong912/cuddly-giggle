"""OCR runtime shared by the ZeroGPU entrypoint and local validation."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from config.config import Settings

SUPPORTED_SUFFIXES = ('.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff',
                      '.doc', '.docx', '.xls', '.xlsx', '.xlsm')
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
PDF_MAX_PAGES = 3


def demo_settings() -> Settings:
    return replace(
        Settings(),
        openai_api_key='', database_url='', llama_server_autostart=False,
        ocr_device='gpu:0', ocr_inference_engine='transformers',
        paddleocr_vl_pipeline_version='v1.6', paddleocr_vl_use_gguf=False,
        paddleocr_vl_rec_backend='', paddleocr_vl_rec_server_url='',
        paddleocr_vl_auto_rotate=False, paddleocr_vl_use_doc_unwarping=False,
        ocr_external_rotation=False, preprocess_enabled=False,
        preprocess_save_images=False, table_only_output=False,
        max_upload_bytes=MAX_UPLOAD_BYTES, pdf_max_pages=PDF_MAX_PAGES,
    )


def ui_config() -> dict[str, object]:
    return dict(supported_suffixes=list(SUPPORTED_SUFFIXES),
                max_upload_bytes=MAX_UPLOAD_BYTES, pdf_max_pages=PDF_MAX_PAGES)


def validate_input(file_path: str | None) -> Path:
    if not file_path:
        raise ValueError('Select a document first.')
    path = Path(file_path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError('Unsupported document format.')
    size = path.stat().st_size
    if size == 0 or size > MAX_UPLOAD_BYTES:
        raise ValueError('Upload a non-empty document of at most 20 MiB.')
    if path.suffix.lower() == '.pdf':
        import fitz

        with fitz.open(path) as document:
            if document.page_count > PDF_MAX_PAGES:
                raise ValueError('The free GPU demo accepts PDFs of at most 3 pages.')
    return path


def gpu_duration(file_path: str) -> int:
    """Reserve 30 seconds per PDF page, or 30 seconds for another document."""
    path = validate_input(file_path)
    if path.suffix.lower() == '.pdf':
        import fitz

        with fitz.open(path) as document:
            return 30 * max(1, document.page_count)
    return 30
