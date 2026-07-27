"""Choose the local OCR engine from the available hardware."""
from __future__ import annotations

from collections.abc import Callable

from config.config import Settings, settings
from core.engines.base import ParseEngine
from core.engines.fast_paddle import PaddleOCRFastEngine
from core.engines.paddle import PaddleOCRVLEngine


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
    """Return true only when a supported local CUDA runtime is available."""
    try:
        import torch  # type: ignore

        return bool(torch.cuda.is_available())
    except Exception:
        pass

    try:
        import paddle  # type: ignore

        return bool(paddle.device.is_compiled_with_cuda())
    except Exception:
        return False
