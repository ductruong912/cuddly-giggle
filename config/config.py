from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import site

# pyrefly: ignore [missing-import]
from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
# Load from the repo root, not the working directory: a service started from
# elsewhere (Windows service, systemd, `python f:\...\main.py`) must still see .env.
load_dotenv(REPO_ROOT / ".env", override=False)


def _repo_path_from_env(name: str, default: str) -> str:
    value = Path(os.getenv(name, default).strip() or default)
    return str(value if value.is_absolute() else (REPO_ROOT / value).resolve())


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_str(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Settings:

    # --- OpenAI structured extraction ---
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "").strip()
    openai_model: str = _get_str("OPENAI_MODEL", "gpt-5-mini")
    openai_timeout_seconds: float = _get_float("OPENAI_TIMEOUT_SECONDS", 60.0)
    openai_max_retries: int = _get_int("OPENAI_MAX_RETRIES", 2)
    llm_max_input_chars: int = _get_int("LLM_MAX_INPUT_CHARS", 120_000)
    llm_reasoning_effort: str = _get_str("LLM_REASONING_EFFORT", "low").lower()

    # --- Extraction validation & self-healing ---
    # Extra extraction calls allowed when a record fails validation. Each retry
    # runs inside the same LLM slot, so it costs latency, not concurrency.
    llm_self_heal_max_retries: int = _get_int("LLM_SELF_HEAL_MAX_RETRIES", 2)
    # Relative tolerance for quantity x unit_price vs. the stated line total.
    po_line_total_tolerance_ratio: float = _get_float("PO_LINE_TOTAL_TOLERANCE_RATIO", 0.01)

    # --- OCR engines ---
    primary_engine: str                = _get_str("OCR_PRIMARY_ENGINE", "paddleocr_vl")
    ocr_device: str                    = os.getenv("OCR_DEVICE", "").strip()
    ocr_inference_engine: str          = os.getenv("OCR_INFERENCE_ENGINE", "").strip()
    paddleocr_vl_pipeline_version: str = _get_str("PADDLEOCR_VL_PIPELINE_VERSION", "v1.6")
    paddleocr_vl_rec_backend: str      = os.getenv("PADDLEOCR_VL_REC_BACKEND", "").strip()
    paddleocr_vl_rec_server_url: str   = os.getenv("PADDLEOCR_VL_REC_SERVER_URL", "").strip()
    paddleocr_vl_rec_max_concurrency: int = _get_int("PADDLEOCR_VL_REC_MAX_CONCURRENCY", 0)
    paddleocr_vl_rec_api_model_name: str = os.getenv("PADDLEOCR_VL_REC_API_MODEL_NAME", "").strip()
    paddleocr_vl_rec_api_key: str      = os.getenv("PADDLEOCR_VL_REC_API_KEY", "").strip()
    paddleocr_vl_use_gguf: bool        = _get_bool("PADDLEOCR_VL_USE_GGUF", False)
    paddleocr_vl_max_pixels: int       = _get_int("PADDLEOCR_VL_MAX_PIXELS", 1003520)
    paddleocr_vl_markdown_ignore_labels: tuple[str, ...] = tuple(
        item.strip()
        for item in os.getenv("PADDLEOCR_VL_MARKDOWN_IGNORE_LABELS", "").split(",")
        if item.strip()
    )
    fast_ocr_device: str = _get_str("FAST_OCR_DEVICE", "cpu")
    fast_ocr_detection_model_name: str = _get_str(
        "FAST_OCR_DETECTION_MODEL_NAME", "PP-OCRv6_medium_det"
    )
    fast_ocr_recognition_model_name: str = _get_str(
        "FAST_OCR_RECOGNITION_MODEL_NAME", "PP-OCRv6_small_rec"
    )
    fast_ocr_recognition_batch_size: int = _get_int("FAST_OCR_RECOGNITION_BATCH_SIZE", 8)
    fast_ocr_cpu_threads: int = _get_int("FAST_OCR_CPU_THREADS", 4)
    fast_ocr_inference_engine: str = _get_str("FAST_OCR_INFERENCE_ENGINE", "onnxruntime")
    fast_ocr_enable_mkldnn: bool = _get_bool("FAST_OCR_ENABLE_MKLDNN", False)
    fast_ocr_datalab_mode: str = _get_str("FAST_OCR_DATALAB_MODE", "balanced").lower()
    fast_ocr_datalab_timeout_seconds: float = _get_float("FAST_OCR_DATALAB_TIMEOUT_SECONDS", 120.0)
    datalab_api_key: str = os.getenv("DATALAB_API_KEY", "").strip()
    warmup_models_on_startup: bool     = _get_bool("WARMUP_MODELS_ON_STARTUP", False)

    # --- llama.cpp / GGUF bootstrap ---
    auto_download_llama_cpp: bool = _get_bool("AUTO_DOWNLOAD_LLAMA_CPP", False)
    llama_cpp_dir: str = _get_str("LLAMA_CPP_DIR", "llama")
    llama_cpp_models_dir: str = _get_str("LLAMA_CPP_MODELS_DIR", "models")
    llama_cpp_model_file: str = _get_str("LLAMA_CPP_MODEL_FILE", "PaddleOCR-VL-1.6-GGUF.gguf")
    llama_cpp_mmproj_file: str = _get_str("LLAMA_CPP_MMPROJ_FILE", "PaddleOCR-VL-1.6-GGUF-mmproj.gguf")
    llama_cpp_release_url: str = os.getenv("LLAMA_CPP_RELEASE_URL", "").strip()
    llama_cpp_release_flavor: str = _get_str("LLAMA_CPP_RELEASE_FLAVOR", "win-cuda-12.4-x64")

    # --- llama.cpp server autostart ---
    llama_server_autostart: bool = _get_bool("LLAMA_SERVER_AUTOSTART", True)
    llama_server_host: str = _get_str("LLAMA_SERVER_HOST", "127.0.0.1")
    llama_server_port: int = _get_int("LLAMA_SERVER_PORT", 8080)
    llama_server_ctx_size: int = _get_int("LLAMA_SERVER_CTX_SIZE", 4096)
    llama_server_parallel: int = _get_int("LLAMA_SERVER_PARALLEL", 1)
    llama_server_n_gpu_layers: int = _get_int("LLAMA_SERVER_N_GPU_LAYERS", 40)
    llama_server_mmproj_offload: bool = _get_bool("LLAMA_SERVER_MMPROJ_OFFLOAD", True)
    llama_server_flash_attn: str = _get_str("LLAMA_SERVER_FLASH_ATTN", "on")
    llama_server_threads: int = _get_int("LLAMA_SERVER_THREADS", 4)
    llama_server_threads_batch: int = _get_int("LLAMA_SERVER_THREADS_BATCH", 4)
    llama_server_temp: float = _get_float("LLAMA_SERVER_TEMP", 0.0)
    llama_server_log_verbosity: int = _get_int("LLAMA_SERVER_LOG_VERBOSITY", 1)
    llama_server_startup_timeout_seconds: float = _get_float("LLAMA_SERVER_STARTUP_TIMEOUT_SECONDS", 120.0)

    # --- PDF text fast-path ---
    pdf_text_parse_enabled: bool           = _get_bool("PDF_TEXT_PARSE_ENABLED", True)

    # --- Normalizer synthetic confidence heuristic ---
    normalizer_confidence_base: float           = _get_float("NORMALIZER_CONFIDENCE_BASE", 0.55)
    normalizer_confidence_content_weight: float = _get_float("NORMALIZER_CONFIDENCE_CONTENT_WEIGHT", 0.35)
    normalizer_confidence_table_bonus: float    = _get_float("NORMALIZER_CONFIDENCE_TABLE_BONUS", 0.05)
    normalizer_confidence_cap: float            = _get_float("NORMALIZER_CONFIDENCE_CAP", 0.9)

    # --- PDF rasterization for OCR (render each page to an image, OCR per page) ---
    pdf_rasterize_enabled: bool          = _get_bool("PDF_RASTERIZE_ENABLED", True)
    pdf_rasterize_dpi: int               = _get_int("PDF_RASTERIZE_DPI", 200)

    # --- Output filtering ---
    table_only_output: bool              = _get_bool("TABLE_ONLY_OUTPUT", False)

    # --- Rate limiting ---
    rate_limit_default: str = _get_str("RATE_LIMIT_DEFAULT", "30/minute")
    rate_limit_extract: str = _get_str("RATE_LIMIT_EXTRACT", "10/minute")

    # --- Concurrency & admission control ---
    # One GPU and a llama.cpp server started with --parallel 1 serialise most OCR
    # work, so admitting more than a couple of parses at a time only grows the queue.
    ocr_max_concurrency: int = _get_int("OCR_MAX_CONCURRENCY", 2)
    llm_max_concurrency: int = _get_int("LLM_MAX_CONCURRENCY", 8)
    stage_queue_timeout_seconds: float = _get_float("STAGE_QUEUE_TIMEOUT_SECONDS", 30.0)
    # 0 lets the app derive the worker-thread count from the stage limits.
    server_thread_pool_size: int = _get_int("SERVER_THREAD_POOL_SIZE", 0)

    # --- Request guards ---
    max_upload_bytes: int = _get_int("MAX_UPLOAD_BYTES", 50 * 1024 * 1024)
    pdf_max_pages: int = _get_int("PDF_MAX_PAGES", 100)

    # --- Paths & misc ---
    temp_dir: str                        = _get_str("DOC_TEMP_DIR", ".tmp_doc_parse")
    parse_output_dir: str                = _get_str("PARSE_OUTPUT_DIR", "outputs")
    quiet_third_party_logs: bool         = _get_bool("QUIET_THIRD_PARTY_LOGS", True)

    # --- PaddleX / model cache ---
    paddlex_cache_home: str = _repo_path_from_env("PADDLE_PDX_CACHE_HOME", ".paddlex")
    paddlex_disable_model_source_check: bool = _get_bool("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", True)

    def __post_init__(self) -> None:
        if self.fast_ocr_datalab_mode not in {"fast", "balanced", "accurate"}:
            raise ValueError(
                "FAST_OCR_DATALAB_MODE must be one of: fast, balanced, accurate"
            )
        if self.fast_ocr_datalab_timeout_seconds <= 0:
            raise ValueError("FAST_OCR_DATALAB_TIMEOUT_SECONDS must be greater than zero")
        if self.ocr_max_concurrency < 1:
            raise ValueError("OCR_MAX_CONCURRENCY must be at least 1")
        if self.llm_max_concurrency < 1:
            raise ValueError("LLM_MAX_CONCURRENCY must be at least 1")
        if self.stage_queue_timeout_seconds <= 0:
            raise ValueError("STAGE_QUEUE_TIMEOUT_SECONDS must be greater than zero")
        if self.max_upload_bytes < 1:
            raise ValueError("MAX_UPLOAD_BYTES must be at least 1")
        if self.pdf_max_pages < 1:
            raise ValueError("PDF_MAX_PAGES must be at least 1")
        if self.llm_self_heal_max_retries < 0:
            raise ValueError("LLM_SELF_HEAL_MAX_RETRIES cannot be negative")
        if self.po_line_total_tolerance_ratio < 0:
            raise ValueError("PO_LINE_TOTAL_TOLERANCE_RATIO cannot be negative")

    @property
    def resolved_thread_pool_size(self) -> int:
        """Worker threads to allow, sized from the stage limits rather than anyio's default 40.

        Every admitted OCR and LLM request occupies one worker thread, plus a few
        for upload staging and synchronous dependencies. Anyio's default is far
        larger than this machine can usefully run and lets bursts thrash the GPU.
        """
        if self.server_thread_pool_size > 0:
            return self.server_thread_pool_size
        stage_threads = self.ocr_max_concurrency + self.llm_max_concurrency
        return max(8, stage_threads + 4)


# ---------------------------------------------------------------------------
# Module-level initialisation
# ---------------------------------------------------------------------------

settings = Settings()


def _init_directories() -> None:
    Path(settings.paddlex_cache_home).mkdir(parents=True, exist_ok=True)
    Path(settings.parse_output_dir).mkdir(parents=True, exist_ok=True)


def _init_env_defaults() -> None:
    defaults: dict[str, str] = {
        "PADDLE_PDX_CACHE_HOME": settings.paddlex_cache_home,
        "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": (
            "True" if settings.paddlex_disable_model_source_check else "False"
        ),
        "HF_HUB_DISABLE_PROGRESS_BARS": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "GLOG_minloglevel": "2",
        "GLOG_logtostderr": "1",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def _prepend_windows_cuda_paths() -> None:
    if os.name != "nt":
        return

    # NVIDIA CUDA wheels ship DLLs under nvidia/<component>/bin (cu12 layout) or
    # nvidia/<component>/bin/x86_64 (cu13 layout). Scan every component and keep
    # only bin dirs that actually contain DLLs, independent of the CUDA major.
    candidates: list[Path] = []
    for base in site.getsitepackages():
        nvidia_root = Path(base) / "nvidia"
        if not nvidia_root.is_dir():
            continue
        for component in sorted(nvidia_root.iterdir()):
            if not component.is_dir():
                continue
            for bin_dir in (component / "bin", component / "bin" / "x86_64"):
                if bin_dir.is_dir() and any(bin_dir.glob("*.dll")):
                    candidates.append(bin_dir)

    existing = [str(p) for p in candidates]
    if not existing:
        return

    current = os.environ.get("PATH", "")
    path_items = current.split(";") if current else []
    new_items = [p for p in existing if p not in path_items]
    if new_items:
        os.environ["PATH"] = ";".join(new_items + path_items)


_init_directories()
_init_env_defaults()
_prepend_windows_cuda_paths()


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def configure_third_party_logging() -> None:
    if not settings.quiet_third_party_logs:
        return
    try:
        from paddlex.utils import logging as paddlex_logging  # type: ignore
        paddlex_logging.setup_logging("WARNING")
    except Exception:
        pass


def configure_app_logging() -> None:
    for logger_name in ("app", "api", "config", "core", "eval", "services"):
        app_logger = logging.getLogger(logger_name)
        app_logger.setLevel(logging.INFO)
        # Do not propagate: paddlex installs its own root handler on import, so
        # bubbling up would print every application line a second time in its format.
        app_logger.propagate = False

        already_configured = any(
            getattr(h, "_cuddly_giggle_app_handler", False) for h in app_logger.handlers
        )
        if already_configured:
            continue

        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        handler._cuddly_giggle_app_handler = True  # type: ignore[attr-defined]
        app_logger.addHandler(handler)
