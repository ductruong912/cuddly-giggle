"""Choose the local OCR engine from the available hardware."""
from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
import logging
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config.config import Settings
    from core.engines.base import ParseEngine

logger = logging.getLogger(__name__)

class LocalOCRSelector:
    """Prefer the VLM on CUDA-capable machines and PaddleOCR v6 on CPU."""

    def __init__(
        self,
        app_settings: Settings | None = None,
        *,
        gpu_available: Callable[[], bool] | None = None,
        vlm_factory: Callable[[Settings], ParseEngine] | None = None,
        cpu_factory: Callable[[Settings], ParseEngine] | None = None,
    ) -> None:
        if app_settings is None:
            from config.config import settings

            app_settings = settings
        self.settings = app_settings
        self._gpu_available = gpu_available or has_usable_gpu
        self._vlm_factory = vlm_factory
        self._cpu_factory = cpu_factory

    def select(self) -> ParseEngine:
        if self._gpu_available():
            if self._vlm_factory is not None:
                return self._vlm_factory(self.settings)
            from core.engines.paddle import PaddleOCRVLEngine

            return PaddleOCRVLEngine(self.settings)
        if self._cpu_factory is not None:
            return self._cpu_factory(self.settings)
        from core.engines.paddle_fast import PaddleOCRFastEngine

        return PaddleOCRFastEngine(self.settings)


@lru_cache(maxsize=1)
def has_usable_gpu() -> bool:
    """Return true when a CUDA runtime or NVIDIA GPU is available locally.

    Cached: this runs on every request to the local route, and the uncached path
    can spawn `nvidia-smi` and wait up to two seconds. Hardware does not change
    while the process is running.
    """
    try:
        import torch  # type: ignore

        return bool(torch.cuda.is_available())
    except Exception:
        pass

    try:
        import paddle  # type: ignore

        # device_count(), not is_compiled_with_cuda(): the latter reports whether
        # the installed wheel was *built* with CUDA, which paddlepaddle-gpu always
        # was. On a CPU-only machine it returns True and the VLM is selected with
        # no GPU to run it on.
        if paddle.device.cuda.device_count() > 0:
            return True
    except Exception:
        logger.debug("paddle CUDA probe failed; falling back to nvidia-smi", exc_info=True)

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
