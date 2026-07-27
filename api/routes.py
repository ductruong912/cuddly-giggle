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
from fastapi.responses import PlainTextResponse
# pyrefly: ignore [missing-import]
from starlette.concurrency import run_in_threadpool

from config.config import settings
from config.pipeline_logging import pipeline_message, request_logging_context
from core.domain.schemas import (
    LLMExtractionOCRMetadata,
    LLMExtractionResponse,
    ParseDecision,
    ParseOptions,
    ParseResponse,
)
from services.llm_extraction import (
    LLMExtractionError,
    LLMExtractionInputTooLarge,
    LLMExtractionService,
    LLMExtractionUnavailable,
)
from services.orchestrator import ParseOrchestrator
from services.online_orchestrator import OnlineParseOrchestrator
from services.local_ocr_selector import has_usable_gpu
from services.output import save_parse_artifacts, save_extraction_artifacts
from services.vl_runtime import VLRuntimeManager


logger = logging.getLogger(__name__)


# =====================================================================================
# Dependencies
# =====================================================================================

@lru_cache(maxsize=1)
def get_orchestrator() -> ParseOrchestrator:
    return ParseOrchestrator()


@lru_cache(maxsize=1)
def get_online_orchestrator() -> OnlineParseOrchestrator:
    return OnlineParseOrchestrator()


@lru_cache(maxsize=1)
def get_llm_extractor() -> LLMExtractionService:
    return LLMExtractionService()


def get_vl_runtime_manager(request: Request) -> VLRuntimeManager:
    manager = getattr(request.app.state, "vl_runtime_manager", None)
    if manager is None:
        raise RuntimeError("VL runtime manager is not configured")
    return manager


def ensure_gpu_gguf_runtime(request: Request) -> None:
    """Start llama.cpp only when the local GPU route uses the GGUF VLM."""
    if not (has_usable_gpu() and settings.paddleocr_vl_use_gguf):
        return
    try:
        get_vl_runtime_manager(request).ensure_ready()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"VL GGUF runtime is unavailable: {exc}") from exc


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

doc_router = APIRouter(prefix="/v1/extract", tags=["documents"])
ocr_router = APIRouter(prefix="/v1/doc", tags=["documents"])

SUPPORTED_INPUT_SUFFIXES = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
FAST_OCR_INPUT_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


@doc_router.post("/local", response_model=LLMExtractionResponse)
async def extract_local_document(
    request: Request,
    file: UploadFile | None = File(None),
    orchestrator: ParseOrchestrator = Depends(get_orchestrator),
    extractor: LLMExtractionService = Depends(get_llm_extractor),
    _: None = Depends(ensure_gpu_gguf_runtime),
) -> LLMExtractionResponse:
    total_start = time.perf_counter()
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
            request_id = f"req_{uuid.uuid4().hex[:12]}"
            try:
                with temp_path.open("wb") as f:
                    shutil.copyfileobj(uploaded_file.file, f)
                logger.info(
                    pipeline_message(
                        # "PHASE 1",
                        "received file=%s suffix=%s size_bytes=%s",
                        # request_id=request_id,
                    ),
                    uploaded_file.filename or temp_path.name,
                    suffix,
                    temp_path.stat().st_size,
                )
                response = orchestrator.parse(
                    str(temp_path),
                    ParseOptions(),
                    request_id=request_id,
                )
                with request_logging_context(response.request_id):
                    data = extractor.extract(response)
                
                # Save markdown OCR result and structured JSON output
                saved_markdown = save_parse_artifacts(response, uploaded_file.filename or temp_path.name)
                saved_json = save_extraction_artifacts(data, uploaded_file.filename or temp_path.name)

                logger.info(
                    pipeline_message(
                        "COMPLETED",
                        "pages=%s blocks=%s tables=%s total=%.3fs saved_markdown=%s saved_json=%s",
                        request_id=response.request_id,
                    ),
                    len(response.pages),
                    len(response.blocks),
                    len(response.tables),
                    time.perf_counter() - total_start,
                    ",".join(saved_markdown) or "none",
                    ",".join(saved_json) or "none",
                )
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
                logger.error(
                    pipeline_message("FAILED", "unexpected extraction request error", request_id=request_id),
                    exc_info=True,
                )
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


@doc_router.post("/online", response_model=LLMExtractionResponse)
async def extract_online_document(
    request: Request,
    file: UploadFile | None = File(None),
    orchestrator: OnlineParseOrchestrator = Depends(get_online_orchestrator),
    extractor: LLMExtractionService = Depends(get_llm_extractor),
) -> LLMExtractionResponse:
    total_start = time.perf_counter()
    upload_elapsed = 0.0
    ocr_elapsed = 0.0
    llm_elapsed = 0.0
    save_elapsed = 0.0
    if "multipart/form-data" not in request.headers.get("content-type", ""):
        raise HTTPException(status_code=415, detail="Online OCR requires a multipart/form-data file upload.")

    uploaded_file = file
    if uploaded_file is None:
        form = await request.form()
        uploaded_file = form.get("file")
    if not uploaded_file or not (hasattr(uploaded_file, "filename") and hasattr(uploaded_file, "file")):
        raise HTTPException(status_code=400, detail="Missing 'file' field in multipart/form-data upload.")

    suffix = Path(uploaded_file.filename or "").suffix.lower()
    if suffix not in FAST_OCR_INPUT_SUFFIXES:
        raise HTTPException(status_code=400, detail="Online OCR supports PDF and image files only.")

    temp_root = Path(settings.temp_dir)
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_path = temp_root / f"{uuid.uuid4().hex}{suffix}"
    request_id = f"req_{uuid.uuid4().hex[:12]}"
    try:
        stage_start = time.perf_counter()
        with temp_path.open("wb") as staged_file:
            shutil.copyfileobj(uploaded_file.file, staged_file)
        upload_elapsed = time.perf_counter() - stage_start
        logger.info(
            pipeline_message("received online-ocr file=%s suffix=%s size_bytes=%s"),
            uploaded_file.filename or temp_path.name,
            suffix,
            temp_path.stat().st_size,
        )
        stage_start = time.perf_counter()
        response = await run_in_threadpool(
            orchestrator.parse,
            str(temp_path),
            request_id=request_id,
        )
        ocr_elapsed = time.perf_counter() - stage_start
        stage_start = time.perf_counter()
        with request_logging_context(response.request_id):
            data = extractor.extract(response)
        llm_elapsed = time.perf_counter() - stage_start
        stage_start = time.perf_counter()
        saved_markdown = save_parse_artifacts(response, uploaded_file.filename or temp_path.name)
        saved_json = save_extraction_artifacts(data, uploaded_file.filename or temp_path.name)
        save_elapsed = time.perf_counter() - stage_start
        engine_metadata = response.engine_metadata or {}
        provider = str(engine_metadata.get("provider") or ("datalab" if response.engine_name == "datalab" else "local"))
        datalab_runtime = engine_metadata.get("runtime", "n/a")
        cost_breakdown = engine_metadata.get("cost_breakdown")
        datalab_cost = (
            cost_breakdown.get("final_cost_cents", "n/a")
            if isinstance(cost_breakdown, dict)
            else "n/a"
        )
        logger.info(
            pipeline_message(
                "COMPLETED online-ocr pages=%s markdown_chars=%s provider=%s datalab_runtime=%ss datalab_cost_cents=%s upload=%.3fs ocr=%.3fs llm=%.3fs save=%.3fs total=%.3fs saved_markdown=%s saved_json=%s",
                request_id=response.request_id,
            ),
            len(response.pages),
            len(response.markdown or ""),
            provider,
            datalab_runtime,
            datalab_cost,
            upload_elapsed,
            ocr_elapsed,
            llm_elapsed,
            save_elapsed,
            time.perf_counter() - total_start,
            ",".join(saved_markdown) or "none",
            ",".join(saved_json) or "none",
        )
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
        logger.error(pipeline_message("FAILED online-ocr extraction request error", request_id=request_id), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Unexpected online OCR extraction error: {exc}") from exc
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


@ocr_router.post("/ocr", response_class=PlainTextResponse)
def ocr_document(
    file: UploadFile = File(...),
    orchestrator: ParseOrchestrator = Depends(get_orchestrator),
) -> PlainTextResponse:
    """Run local OCR only and return Markdown for debugging."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_INPUT_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported input type. Use PDF, Word, Excel, or image files.")

    temp_root = Path(settings.temp_dir)
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_path = temp_root / f"{uuid.uuid4().hex}{suffix}"
    request_id = f"req_{uuid.uuid4().hex[:12]}"
    try:
        with temp_path.open("wb") as staged_file:
            shutil.copyfileobj(file.file, staged_file)
        response = orchestrator.parse(str(temp_path), ParseOptions(), request_id=request_id)
        save_parse_artifacts(response, file.filename or temp_path.name)
        if not response.markdown:
            raise HTTPException(status_code=500, detail="No markdown output produced.")
        return PlainTextResponse(response.markdown, media_type="text/markdown")
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(pipeline_message("FAILED", "unexpected OCR request error", request_id=request_id), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Unexpected parsing error: {exc}") from exc
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
