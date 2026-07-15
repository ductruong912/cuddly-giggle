"""HTTP routes and the orchestrator dependency."""
from __future__ import annotations

from functools import lru_cache
import logging
from pathlib import Path
import shutil
import time
import uuid

# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Request
# pyrefly: ignore [missing-import]
from fastapi.responses import PlainTextResponse

from app.core.config import settings
from app.domain.schemas import (
    LLMExtractionOCRMetadata,
    LLMExtractionResponse,
    ParseDecision,
    ParseOptions,
    ParseResponse,
)
from app.services.llm_extraction import (
    LLMExtractionError,
    LLMExtractionInputTooLarge,
    LLMExtractionService,
    LLMExtractionUnavailable,
)
from app.services.orchestrator import ParseOrchestrator
from app.services.output import save_parse_artifacts, save_extraction_artifacts


logger = logging.getLogger(__name__)


# =====================================================================================
# Dependencies
# =====================================================================================

@lru_cache(maxsize=1)
def get_orchestrator() -> ParseOrchestrator:
    return ParseOrchestrator()


@lru_cache(maxsize=1)
def get_llm_extractor() -> LLMExtractionService:
    return LLMExtractionService()


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


@doc_router.post("/extract", response_model=LLMExtractionResponse)
async def extract_document(
    request: Request,
    file: UploadFile | None = File(None),
    orchestrator: ParseOrchestrator = Depends(get_orchestrator),
    extractor: LLMExtractionService = Depends(get_llm_extractor),
) -> LLMExtractionResponse:
    content_type = request.headers.get("content-type", "")

    # 1. Handle multipart/form-data (File Upload)
    if "multipart/form-data" in content_type:
        uploaded_file = file
        if uploaded_file is None:
            form = await request.form()
            uploaded_file = form.get("file")
        if not uploaded_file or not (hasattr(uploaded_file, "filename") and hasattr(uploaded_file, "file")):
            raise HTTPException(status_code=400, detail="Missing 'file' field in multipart/form-data upload.")

        suffix = Path(uploaded_file.filename or "").suffix.lower()

        # 1a. If it's a Markdown file, bypass OCR and extract directly
        if suffix in {".md", ".markdown"}:
            try:
                markdown = (await uploaded_file.read()).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise HTTPException(status_code=400, detail="Markdown file must be UTF-8 encoded.") from exc

            parse_response = ParseResponse(
                request_id=f"llm_{uuid.uuid4().hex[:12]}",
                decision=ParseDecision(reason="Provided parsed Markdown via file upload."),
                pages=[],
                blocks=[],
                tables=[],
                reading_order=[],
                markdown=markdown,
            )
            try:
                data = extractor.extract(parse_response)
                save_extraction_artifacts(data, uploaded_file.filename or "extraction.json")
                return LLMExtractionResponse(
                    request_id=parse_response.request_id,
                    ocr=LLMExtractionOCRMetadata(
                        decision=parse_response.decision.reason,
                        page_count=0,
                    ),
                    data=data,
                )
            except LLMExtractionInputTooLarge as exc:
                raise HTTPException(status_code=413, detail=str(exc)) from exc
            except LLMExtractionUnavailable as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except LLMExtractionError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        # 1b. If it's a supported document format, run the full pipeline (OCR + LLM)
        elif suffix in SUPPORTED_INPUT_SUFFIXES:
            temp_root = Path(settings.temp_dir)
            temp_root.mkdir(parents=True, exist_ok=True)
            temp_path = temp_root / f"{uuid.uuid4().hex}{suffix}"
            try:
                with temp_path.open("wb") as f:
                    shutil.copyfileobj(uploaded_file.file, f)
                response = orchestrator.parse(
                    str(temp_path),
                    ParseOptions(enable_fallback=settings.default_enable_fallback),
                )
                data = extractor.extract(response)
                
                # Save markdown OCR result and structured JSON output
                save_parse_artifacts(response, uploaded_file.filename or temp_path.name)
                save_extraction_artifacts(data, uploaded_file.filename or temp_path.name)

                logger.info("llm extraction complete request_id=%s pages=%s", response.request_id, len(response.pages))
                return LLMExtractionResponse(
                    request_id=response.request_id,
                    ocr=LLMExtractionOCRMetadata(
                        decision=response.decision.reason,
                        page_count=len(response.pages),
                    ),
                    data=data,
                )
            except LLMExtractionInputTooLarge as exc:
                raise HTTPException(status_code=413, detail=str(exc)) from exc
            except LLMExtractionUnavailable as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except LLMExtractionError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Unexpected extraction error: {exc}") from exc
            finally:
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)
        else:
            raise HTTPException(
                status_code=400,
                detail="Unsupported input type. Use PDF, Word, Excel, Markdown, or image files."
            )

    # 2. Handle plain text / markdown bodies
    elif "text/markdown" in content_type or "text/plain" in content_type:
        body_bytes = await request.body()
        try:
            markdown = body_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Request body must be UTF-8 encoded.") from exc

        parse_response = ParseResponse(
            request_id=f"llm_{uuid.uuid4().hex[:12]}",
            decision=ParseDecision(reason="Provided raw Markdown body."),
            pages=[],
            blocks=[],
            tables=[],
            reading_order=[],
            markdown=markdown,
        )
        try:
            data = extractor.extract(parse_response)
            return LLMExtractionResponse(
                request_id=parse_response.request_id,
                ocr=LLMExtractionOCRMetadata(
                    decision=parse_response.decision.reason,
                    page_count=0,
                ),
                data=data,
            )
        except LLMExtractionInputTooLarge as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except LLMExtractionUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except LLMExtractionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # 3. Handle application/json payloads
    elif "application/json" in content_type:
        try:
            body_json = await request.json()
            if not isinstance(body_json, dict) or "markdown" not in body_json:
                raise HTTPException(status_code=400, detail="JSON payload must be an object containing a 'markdown' key.")
            markdown = str(body_json["markdown"])
        except Exception as exc:
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(status_code=400, detail="Invalid JSON body.") from exc

        parse_response = ParseResponse(
            request_id=f"llm_{uuid.uuid4().hex[:12]}",
            decision=ParseDecision(reason="Provided Markdown via JSON payload."),
            pages=[],
            blocks=[],
            tables=[],
            reading_order=[],
            markdown=markdown,
        )
        try:
            data = extractor.extract(parse_response)
            return LLMExtractionResponse(
                request_id=parse_response.request_id,
                ocr=LLMExtractionOCRMetadata(
                    decision=parse_response.decision.reason,
                    page_count=0,
                ),
                data=data,
            )
        except LLMExtractionInputTooLarge as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except LLMExtractionUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except LLMExtractionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    else:
        raise HTTPException(
            status_code=415,
            detail="Unsupported Content-Type. Use multipart/form-data, text/markdown, text/plain, or application/json."
        )


@doc_router.post("/ocr", response_class=PlainTextResponse)
def ocr_document(
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
