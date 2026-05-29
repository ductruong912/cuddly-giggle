from __future__ import annotations

import logging
from pathlib import Path
import shutil
import time
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.dependencies import get_orchestrator
from app.core.config import settings
from app.domain.schemas import LangHint, OutputFormat, ParseOptions, ParseResponse
from app.services.artifacts import save_parse_artifacts
from app.services.orchestrator import ParseOrchestrator

router = APIRouter(prefix="/v1/doc", tags=["documents"])
logger = logging.getLogger(__name__)

SUPPORTED_INPUT_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


# NOTE: declared as a sync `def` (not `async def`) on purpose. The body performs
# blocking work (file copy + synchronous OCR inference / subprocess), so Starlette
# runs it in its worker threadpool, keeping the event loop free for other requests.
# Concurrent parses are serialized on the engine's inference lock (see paddle_base).
@router.post("/parse", response_model=ParseResponse)
def parse_document(
    file: UploadFile = File(...),
    lang_hint: LangHint = Form(default=LangHint.auto),
    output_format: OutputFormat = Form(default=OutputFormat.both),
    enable_fallback: bool = Form(default=settings.default_enable_fallback),
    output_basename: str | None = Form(default=None),
    orchestrator: ParseOrchestrator = Depends(get_orchestrator),
) -> ParseResponse:
    total_start = time.perf_counter()
    upload_elapsed = 0.0
    parse_elapsed = 0.0
    save_elapsed = 0.0
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_INPUT_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported input type. Use PDF or image files.")

    temp_root = Path(settings.temp_dir)
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_path = temp_root / f"{uuid.uuid4().hex}{suffix}"

    try:
        stage_start = time.perf_counter()
        with temp_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        upload_elapsed = time.perf_counter() - stage_start
        options = ParseOptions(
            lang_hint=lang_hint,
            output_format=output_format,
            enable_fallback=enable_fallback,
        )
        stage_start = time.perf_counter()
        response = orchestrator.parse(str(temp_path), options)
        parse_elapsed = time.perf_counter() - stage_start
        stage_start = time.perf_counter()
        saved_files = save_parse_artifacts(
            response=response,
            input_filename=file.filename or temp_path.name,
            output_format=output_format,
            output_basename=output_basename,
        )
        save_elapsed = time.perf_counter() - stage_start
        final_response = response.model_copy(update={"saved_files": saved_files})
        logger.info(
            "api timings request_id=%s upload=%.3fs parse=%.3fs save=%.3fs total=%.3fs",
            response.request_id,
            upload_elapsed,
            parse_elapsed,
            save_elapsed,
            time.perf_counter() - total_start,
        )
        return final_response
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected parsing error: {exc}") from exc
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
