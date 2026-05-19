from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import site


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    primary_engine: str = os.getenv("OCR_PRIMARY_ENGINE", "paddleocr_vl_1_5")
    fallback_engine: str = os.getenv("OCR_FALLBACK_ENGINE", "pp_structure_v3")
    default_enable_fallback: bool = _get_bool("DEFAULT_ENABLE_FALLBACK", True)
    ocr_device: str = os.getenv("OCR_DEVICE", "").strip()
    ocr_inference_engine: str = os.getenv("OCR_INFERENCE_ENGINE", "").strip()
    qwen_verifier_enabled: bool = _get_bool("QWEN_VERIFIER_ENABLED", False)
    qwen_verifier_base_url: str = os.getenv("QWEN_VERIFIER_BASE_URL", "")
    qwen_verifier_model: str = os.getenv("QWEN_VERIFIER_MODEL", "Qwen/Qwen3-VL-8B-Instruct")
    qwen_verifier_api_key: str = os.getenv("QWEN_VERIFIER_API_KEY", "")
    confidence_pass_threshold: float = _get_float("CONFIDENCE_PASS_THRESHOLD", 0.84)
    confidence_borderline_threshold: float = _get_float("CONFIDENCE_BORDERLINE_THRESHOLD", 0.68)
    quality_fail_threshold: float = _get_float("QUALITY_FAIL_THRESHOLD", 0.62)
    temp_dir: str = os.getenv("DOC_TEMP_DIR", ".tmp_doc_parse")
    parse_output_dir: str = os.getenv("PARSE_OUTPUT_DIR", "outputs")
    quiet_third_party_logs: bool = _get_bool("QUIET_THIRD_PARTY_LOGS", True)
    paddlex_cache_home: str = os.getenv(
        "PADDLE_PDX_CACHE_HOME",
        str((Path.cwd() / ".paddlex").resolve()),
    )
    paddlex_disable_model_source_check: bool = _get_bool("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", True)


settings = Settings()
Path(settings.paddlex_cache_home).mkdir(parents=True, exist_ok=True)
Path(settings.parse_output_dir).mkdir(parents=True, exist_ok=True)
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", settings.paddlex_cache_home)
os.environ.setdefault(
    "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK",
    "True" if settings.paddlex_disable_model_source_check else "False",
)
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("GLOG_logtostderr", "1")


def _prepend_windows_cuda_paths() -> None:
    if os.name != "nt":
        return
    candidates: list[Path] = []
    for base in site.getsitepackages():
        root = Path(base) / "nvidia"
        candidates.extend(
            [
                root / "cu13" / "bin",
                root / "cu13" / "bin" / "x86_64",
                root / "cudnn" / "bin",
            ]
        )

    existing = [str(p) for p in candidates if p.exists()]
    if not existing:
        return

    current = os.environ.get("PATH", "")
    path_items = current.split(";") if current else []
    new_items = [p for p in existing if p not in path_items]
    if new_items:
        os.environ["PATH"] = ";".join(new_items + path_items)


_prepend_windows_cuda_paths()


def configure_third_party_logging() -> None:
    if not settings.quiet_third_party_logs:
        return
    try:
        from paddlex.utils import logging as paddlex_logging  # type: ignore

        paddlex_logging.setup_logging("WARNING")
    except Exception:
        pass
