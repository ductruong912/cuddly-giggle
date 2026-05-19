from __future__ import annotations

from pathlib import Path
import shutil
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.dependencies import get_orchestrator
from app.core.config import settings
from app.domain.schemas import LangHint, OutputFormat, ParseOptions, ParseResponse
from app.services.artifacts import save_parse_artifacts
from app.services.orchestrator import ParseOrchestrator

router = APIRouter(prefix="/v1/doc", tags=["documents"])

SUPPORTED_INPUT_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


@router.post("/parse", response_model=ParseResponse)
async def parse_document(
    file: UploadFile = File(...),
    lang_hint: LangHint = Form(default=LangHint.auto),
    output_format: OutputFormat = Form(default=OutputFormat.both),
    enable_fallback: bool = Form(default=settings.default_enable_fallback),
    output_basename: str | None = Form(default=None),
    orchestrator: ParseOrchestrator = Depends(get_orchestrator),
) -> ParseResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_INPUT_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported input type. Use PDF or image files.")

    temp_root = Path(settings.temp_dir)
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_path = temp_root / f"{uuid.uuid4().hex}{suffix}"

    try:
        with temp_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        options = ParseOptions(
            lang_hint=lang_hint,
            output_format=output_format,
            enable_fallback=enable_fallback,
        )
        response = orchestrator.parse(str(temp_path), options)
        saved_files = save_parse_artifacts(
            response=response,
            input_filename=file.filename or temp_path.name,
            output_format=output_format,
            output_basename=output_basename,
        )
        return response.model_copy(update={"saved_files": saved_files})
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected parsing error: {exc}") from exc
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
