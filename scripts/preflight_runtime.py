from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any

# Ensure repo root is importable when running as `python scripts/preflight_runtime.py`.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    # Importing app config applies default env bootstrap used by the service.
    from app.core.config import settings as app_settings
except Exception:
    app_settings = None


def _find_spec(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _nvidia_smi() -> str:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return (result.stderr or "").strip() or "unavailable"
    except Exception:
        return "unavailable"


def _safe_import_paddle() -> dict[str, Any]:
    out: dict[str, Any] = {"installed": False}
    if not _find_spec("paddle"):
        return out
    try:
        import paddle

        out["installed"] = True
        out["version"] = getattr(paddle, "__version__", "unknown")
        out["compiled_with_cuda"] = bool(paddle.is_compiled_with_cuda())
        try:
            out["device"] = paddle.device.get_device()
        except Exception as exc:
            out["device"] = f"error: {exc}"
        try:
            out["cuda_device_count"] = int(paddle.device.cuda.device_count())
        except Exception:
            out["cuda_device_count"] = 0
    except Exception as exc:
        out["error"] = str(exc)
    return out


def main() -> None:
    repo = Path.cwd()
    paddlex_cache = os.getenv(
        "PADDLE_PDX_CACHE_HOME",
        str((repo / ".paddlex").resolve()),
    )
    model_root = Path(paddlex_cache) / "official_models"

    payload = {
        "python": {
            "executable": sys.executable,
            "version": platform.python_version(),
            "platform": platform.platform(),
        },
        "packages": {
            "paddle": _find_spec("paddle"),
            "paddleocr": _find_spec("paddleocr"),
            "paddlex": _find_spec("paddlex"),
        },
        "paddle_runtime": _safe_import_paddle(),
        "env": {
            "OCR_DEVICE": os.getenv("OCR_DEVICE", ""),
            "OCR_INFERENCE_ENGINE": os.getenv("OCR_INFERENCE_ENGINE", ""),
            "PADDLE_PDX_CACHE_HOME": paddlex_cache,
            "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": os.getenv(
                "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", ""
            ),
        },
        "service_defaults": {
            "loaded": app_settings is not None,
            "paddlex_cache_home": getattr(app_settings, "paddlex_cache_home", ""),
            "paddlex_disable_model_source_check": getattr(
                app_settings, "paddlex_disable_model_source_check", None
            ),
        },
        "model_cache": {
            "exists": model_root.exists(),
            "path": str(model_root),
            "models": sorted([p.name for p in model_root.iterdir()]) if model_root.exists() else [],
        },
        "nvidia_smi": _nvidia_smi(),
    }

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
