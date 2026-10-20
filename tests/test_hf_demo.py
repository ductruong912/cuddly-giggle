"""ZeroGPU deployment guards that do not import cloud/GPU dependencies."""
from pathlib import Path

import fitz
import pytest

from deploy.huggingface.runtime import demo_settings, gpu_duration, ui_config, validate_input
from scripts.prepare_hf_demo import prepare_backend


def test_demo_uses_transformers_without_paid_services():
    settings = demo_settings()
    assert settings.ocr_inference_engine == 'transformers'
    assert settings.ocr_device == 'gpu:0'
    assert settings.openai_api_key == ''
    assert settings.database_url == ''
    assert settings.llama_server_autostart is False
    assert settings.paddleocr_vl_use_gguf is False


def test_pdf_limit_is_enforced_before_inference(tmp_path: Path):
    path = tmp_path / 'long.pdf'
    with fitz.open() as document:
        for _ in range(ui_config()['pdf_max_pages'] + 1):
            document.new_page()
        document.save(path)
    with pytest.raises(ValueError, match='at most 3 pages'):
        validate_input(str(path))


@pytest.mark.parametrize('pages', [1, 2, 3])
def test_gpu_reservation_scales_with_pdf_pages(tmp_path: Path, pages: int):
    path = tmp_path / 'document.pdf'
    with fitz.open() as document:
        for _ in range(pages):
            document.new_page()
        document.save(path)
    assert gpu_duration(str(path)) == 30 * pages


def test_image_does_not_reserve_the_entire_anonymous_quota(tmp_path: Path):
    path = tmp_path / 'scan.png'
    path.write_bytes(b'image placeholder')
    assert gpu_duration(str(path)) == 30


def test_rejects_empty_unsupported_and_oversized_uploads(tmp_path: Path):
    empty = tmp_path / 'empty.png'
    empty.touch()
    with pytest.raises(ValueError, match='non-empty'):
        validate_input(str(empty))
    with pytest.raises(ValueError, match='Unsupported'):
        validate_input(str(tmp_path / '.env'))
    with empty.open('wb') as stream:
        stream.truncate(ui_config()['max_upload_bytes'] + 1)
    with pytest.raises(ValueError, match='20 MiB'):
        validate_input(str(empty))


def test_export_contains_only_deployment_files_and_python_sources(tmp_path: Path):
    destination = tmp_path / 'backend'
    prepare_backend(destination)
    files = {path.relative_to(destination).as_posix()
             for path in destination.rglob('*') if path.is_file()}
    allowed_root = {'app.py', 'requirements.txt', 'packages.txt', 'README.md', 'LICENSE'}
    for name in files:
        assert name in allowed_root or (
            name.endswith('.py') and name.split('/')[0] in {'config', 'core', 'services', 'deploy'}
        ), name
    assert 'deploy/huggingface/runtime.py' in files
    assert 'services/orchestrator.py' in files
    assert not any('.env' in name or '__pycache__' in name for name in files)
