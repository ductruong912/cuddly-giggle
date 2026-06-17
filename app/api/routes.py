"""HTTP routes and the orchestrator dependency."""
from __future__ import annotations

from functools import lru_cache
import logging
from pathlib import Path
import shutil
import time
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse

from app.core.config import settings
from app.domain.schemas import ParseOptions
from app.services.orchestrator import ParseOrchestrator
from app.services.output import save_parse_artifacts


logger = logging.getLogger(__name__)


# =====================================================================================
# Dependencies
# =====================================================================================

@lru_cache(maxsize=1)
def get_orchestrator() -> ParseOrchestrator:
    return ParseOrchestrator()


# =====================================================================================
# Health
# =====================================================================================

health_router = APIRouter(tags=["health"])


@health_router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


# =====================================================================================
# Documents
# =====================================================================================

doc_router = APIRouter(prefix="/v1/doc", tags=["documents"])

SUPPORTED_INPUT_SUFFIXES = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


@doc_router.post("/parse", response_class=PlainTextResponse)
def parse_document(
    file: UploadFile = File(...),
    orchestrator: ParseOrchestrator = Depends(get_orchestrator),
) -> PlainTextResponse:
    total_start = time.perf_counter()
    upload_elapsed = 0.0
    parse_elapsed = 0.0
    save_elapsed = 0.0
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_INPUT_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported input type. Use PDF, Word, Excel, or image files.")

    temp_root = Path(settings.temp_dir)
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_path = temp_root / f"{uuid.uuid4().hex}{suffix}"

    try:
        stage_start = time.perf_counter()
        with temp_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        upload_elapsed = time.perf_counter() - stage_start
        options = ParseOptions(
            enable_fallback=settings.default_enable_fallback,
        )
        stage_start = time.perf_counter()
        response = orchestrator.parse(str(temp_path), options)
        parse_elapsed = time.perf_counter() - stage_start
        stage_start = time.perf_counter()
        saved_files = save_parse_artifacts(
            response=response,
            input_filename=file.filename or temp_path.name,
        )
        save_elapsed = time.perf_counter() - stage_start
        if not response.markdown:
            raise HTTPException(status_code=500, detail="No markdown output produced.")
        logger.info(
            "api timings request_id=%s upload=%.3fs parse=%.3fs save=%.3fs total=%.3fs saved_files=%s",
            response.request_id,
            upload_elapsed,
            parse_elapsed,
            save_elapsed,
            time.perf_counter() - total_start,
            saved_files,
        )
        return PlainTextResponse(response.markdown, media_type="text/markdown")
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected parsing error: {exc}") from exc
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
