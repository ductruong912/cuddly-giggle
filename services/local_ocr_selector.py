"""Choose the local OCR engine from the available hardware."""
from __future__ import annotations

from collections.abc import Callable
import logging
import subprocess

from config.config import Settings, settings
from core.engines.base import ParseEngine
from core.engines.fast_paddle import PaddleOCRFastEngine
from core.engines.paddle import PaddleOCRVLEngine

logger = logging.getLogger(__name__)

class LocalOCRSelector:
    """Prefer the VLM on CUDA-capable machines and PaddleOCR v6 on CPU."""

    def __init__(
        self,
        app_settings: Settings = settings,
        *,
        gpu_available: Callable[[], bool] | None = None,
        vlm_factory: Callable[[Settings], ParseEngine] = PaddleOCRVLEngine,
        cpu_factory: Callable[[Settings], ParseEngine] = PaddleOCRFastEngine,
    ) -> None:
        self.settings = app_settings
        self._gpu_available = gpu_available or has_usable_gpu
        self._vlm_factory = vlm_factory
        self._cpu_factory = cpu_factory

    def select(self) -> ParseEngine:
        if self._gpu_available():
            return self._vlm_factory(self.settings)
        return self._cpu_factory(self.settings)


def has_usable_gpu() -> bool:
    """Return true when a CUDA runtime or NVIDIA GPU is available locally."""
    try:
        import torch  # type: ignore

        return bool(torch.cuda.is_available())
    except Exception:
        pass

    try:
        import paddle  # type: ignore

        if paddle.device.is_compiled_with_cuda():
            return True
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def log_gpu_availability(*, gpu_available: Callable[[], bool] = has_usable_gpu) -> bool:
    """Log the hardware decision made for local OCR at application startup."""
    available = gpu_available()
    engine = "PaddleOCR-VL" if available else "PaddleOCR v6"
    hardware = "GPU detected" if available else "CPU only"
    logger.info("local OCR hardware: %s; engine=%s", hardware, engine)
    return available
