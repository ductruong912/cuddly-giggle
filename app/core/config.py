from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import site

from dotenv import load_dotenv


load_dotenv(Path.cwd() / ".env", override=False)


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
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Settings:

    # --- OCR engines ---
    primary_engine: str                = os.getenv("OCR_PRIMARY_ENGINE", "paddleocr_vl")
    fallback_engine: str               = os.getenv("OCR_FALLBACK_ENGINE", "pp_structure_v3")
    default_enable_fallback: bool      = _get_bool("DEFAULT_ENABLE_FALLBACK", True)
    ocr_device: str                    = os.getenv("OCR_DEVICE", "").strip()
    ocr_inference_engine: str          = os.getenv("OCR_INFERENCE_ENGINE", "").strip()
    paddleocr_vl_pipeline_version: str = os.getenv("PADDLEOCR_VL_PIPELINE_VERSION", "v1.6").strip()
    paddleocr_vl_rec_backend: str      = os.getenv("PADDLEOCR_VL_REC_BACKEND", "").strip()
    paddleocr_vl_rec_server_url: str   = os.getenv("PADDLEOCR_VL_REC_SERVER_URL", "").strip()
    paddleocr_vl_rec_max_concurrency: int = _get_int("PADDLEOCR_VL_REC_MAX_CONCURRENCY", 0)
    paddleocr_vl_rec_api_model_name: str = os.getenv("PADDLEOCR_VL_REC_API_MODEL_NAME", "").strip()
    paddleocr_vl_rec_api_key: str      = os.getenv("PADDLEOCR_VL_REC_API_KEY", "").strip()
    paddleocr_vl_use_gguf: bool        = _get_bool("PADDLEOCR_VL_USE_GGUF", False)
    warmup_models_on_startup: bool     = _get_bool("WARMUP_MODELS_ON_STARTUP", True)

    # --- llama.cpp / GGUF bootstrap ---
    auto_download_llama_cpp: bool = _get_bool("AUTO_DOWNLOAD_LLAMA_CPP", False)
    llama_cpp_dir: str = os.getenv("LLAMA_CPP_DIR", "llama").strip()
    llama_cpp_models_dir: str = os.getenv("LLAMA_CPP_MODELS_DIR", "models").strip()
    llama_cpp_release_url: str = os.getenv("LLAMA_CPP_RELEASE_URL", "").strip()
    llama_cpp_release_flavor: str = os.getenv("LLAMA_CPP_RELEASE_FLAVOR", "win-cuda-cu13.3-x64").strip()

    # --- llama.cpp server autostart ---
    llama_server_autostart: bool = _get_bool("LLAMA_SERVER_AUTOSTART", True)
    llama_server_host: str = os.getenv("LLAMA_SERVER_HOST", "127.0.0.1").strip()
    llama_server_port: int = _get_int("LLAMA_SERVER_PORT", 8080)
    llama_server_ctx_size: int = _get_int("LLAMA_SERVER_CTX_SIZE", 4096)
    llama_server_parallel: int = _get_int("LLAMA_SERVER_PARALLEL", 1)
    llama_server_n_gpu_layers: int = _get_int("LLAMA_SERVER_N_GPU_LAYERS", 40)
    llama_server_mmproj_offload: bool = _get_bool("LLAMA_SERVER_MMPROJ_OFFLOAD", True)
    llama_server_flash_attn: str = os.getenv("LLAMA_SERVER_FLASH_ATTN", "on").strip()
    llama_server_threads: int = _get_int("LLAMA_SERVER_THREADS", 4)
    llama_server_threads_batch: int = _get_int("LLAMA_SERVER_THREADS_BATCH", 4)
    llama_server_temp: float = _get_float("LLAMA_SERVER_TEMP", 0.0)
    llama_server_startup_timeout_seconds: float = _get_float("LLAMA_SERVER_STARTUP_TIMEOUT_SECONDS", 120.0)

    # --- Confidence thresholds ---
    confidence_pass_threshold: float        = _get_float("CONFIDENCE_PASS_THRESHOLD", 0.84)
    confidence_borderline_threshold: float  = _get_float("CONFIDENCE_BORDERLINE_THRESHOLD", 0.68)
    quality_fail_threshold: float           = _get_float("QUALITY_FAIL_THRESHOLD", 0.62)
    # How much higher the fallback page confidence must be to override primary.
    merge_fallback_confidence_margin: float = _get_float("MERGE_FALLBACK_CONFIDENCE_MARGIN", 0.08)

    # --- Image quality detection (images only; PDFs use a neutral default) ---
    quality_blur_var_threshold: float          = _get_float("QUALITY_BLUR_VAR_THRESHOLD", 110.0)
    quality_dark_mean_threshold: float         = _get_float("QUALITY_DARK_MEAN_THRESHOLD", 55.0)
    quality_bright_mean_threshold: float       = _get_float("QUALITY_BRIGHT_MEAN_THRESHOLD", 220.0)
    quality_low_contrast_std_threshold: float  = _get_float("QUALITY_LOW_CONTRAST_STD_THRESHOLD", 24.0)
    quality_skew_deg_threshold: float          = _get_float("QUALITY_SKEW_DEG_THRESHOLD", 3.0)
    quality_min_resolution_px: int             = _get_int("QUALITY_MIN_RESOLUTION_PX", 1200)
    quality_screen_photo_border_diff: float    = _get_float("QUALITY_SCREEN_PHOTO_BORDER_DIFF", 30.0)

    # --- Quality score penalties (subtracted from 1.0 per detected flag) ---
    quality_penalty_skew: float          = _get_float("QUALITY_PENALTY_SKEW", 0.14)
    quality_penalty_blur: float          = _get_float("QUALITY_PENALTY_BLUR", 0.20)
    quality_penalty_illumination: float  = _get_float("QUALITY_PENALTY_ILLUMINATION", 0.14)
    quality_penalty_screen_photo: float  = _get_float("QUALITY_PENALTY_SCREEN_PHOTO", 0.18)
    quality_penalty_low_resolution: float = _get_float("QUALITY_PENALTY_LOW_RESOLUTION", 0.10)

    # --- Quality detector internals ---
    # PDF/unreadable scores straddle quality_fail_threshold, deciding the quality branch.
    quality_pdf_default_score: float           = _get_float("QUALITY_PDF_DEFAULT_SCORE", 0.9)
    quality_unreadable_image_score: float      = _get_float("QUALITY_UNREADABLE_IMAGE_SCORE", 0.6)
    quality_canny_threshold1: int              = _get_int("QUALITY_CANNY_THRESHOLD1", 50)
    quality_canny_threshold2: int              = _get_int("QUALITY_CANNY_THRESHOLD2", 150)
    quality_hough_threshold: int               = _get_int("QUALITY_HOUGH_THRESHOLD", 180)
    quality_skew_max_lines: int                = _get_int("QUALITY_SKEW_MAX_LINES", 80)
    quality_screen_photo_border_fraction: float = _get_float("QUALITY_SCREEN_PHOTO_BORDER_FRACTION", 0.03)

    # --- PDF text fast-path ---
    # Skips OCR when a digital PDF already has a usable embedded text layer.
    pdf_text_parse_enabled: bool           = _get_bool("PDF_TEXT_PARSE_ENABLED", True)
    pdf_text_min_total_chars: int          = _get_int("PDF_TEXT_MIN_TOTAL_CHARS", 80)
    pdf_text_min_chars_per_text_page: int  = _get_int("PDF_TEXT_MIN_CHARS_PER_TEXT_PAGE", 40)
    pdf_text_min_text_pages_ratio: float   = _get_float("PDF_TEXT_MIN_TEXT_PAGES_RATIO", 1.0)
    pdf_text_confidence: float             = _get_float("PDF_TEXT_CONFIDENCE", 0.98)


    # --- Word text fast-path ---
    # DOCX is parsed natively. Legacy DOC is converted to DOCX with LibreOffice when available.
    word_text_confidence: float = _get_float("WORD_TEXT_CONFIDENCE", 0.99)

    # --- Excel text fast-path ---
    # XLSX/XLSM are parsed natively. Legacy XLS is converted to XLSX with LibreOffice when available.
    excel_text_confidence: float = _get_float("EXCEL_TEXT_CONFIDENCE", 0.99)

    # --- Normalizer synthetic confidence heuristic ---
    # Used only when an engine returns no numeric score.
    normalizer_confidence_base: float           = _get_float("NORMALIZER_CONFIDENCE_BASE", 0.55)
    normalizer_confidence_content_weight: float = _get_float("NORMALIZER_CONFIDENCE_CONTENT_WEIGHT", 0.35)
    normalizer_confidence_table_bonus: float    = _get_float("NORMALIZER_CONFIDENCE_TABLE_BONUS", 0.05)
    normalizer_confidence_cap: float            = _get_float("NORMALIZER_CONFIDENCE_CAP", 0.9)

    # --- Paths & misc ---
    temp_dir: str                        = os.getenv("DOC_TEMP_DIR", ".tmp_doc_parse")
    parse_output_dir: str                = os.getenv("PARSE_OUTPUT_DIR", "outputs")
    quiet_third_party_logs: bool         = _get_bool("QUIET_THIRD_PARTY_LOGS", True)

    # --- PaddleX / model cache ---
    paddlex_cache_home: str = os.getenv(
        "PADDLE_PDX_CACHE_HOME",
        str((Path.cwd() / ".paddlex").resolve()),
    )
    paddlex_disable_model_source_check: bool = _get_bool("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", True)


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

    candidates: list[Path] = []
    for base in site.getsitepackages():
        root = Path(base) / "nvidia"
        candidates.extend([
            root / "cu13" / "bin",
            root / "cu13" / "bin" / "x86_64",
            root / "cudnn" / "bin",
        ])

    existing = [str(p) for p in candidates if p.exists()]
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
    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.INFO)
    app_logger.propagate = True

    already_configured = any(
        getattr(h, "_cuddly_giggle_app_handler", False) for h in app_logger.handlers
    )
    if already_configured:
        return

    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("INFO:     %(message)s"))
    handler._cuddly_giggle_app_handler = True  # type: ignore[attr-defined]
    app_logger.addHandler(handler)
