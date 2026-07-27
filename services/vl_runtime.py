"""Thread-safe lifecycle management for the optional PaddleOCR-VL runtime."""
from __future__ import annotations

from collections.abc import Callable
import threading
from typing import Any


class VLRuntimeManager:
    """Prepare the VL runtime at most once, when a VL route first needs it."""

    def __init__(
        self,
        *,
        configure_runtime: Callable[[], Any | None],
        warmup: Callable[[], None],
        stop_runtime: Callable[[Any], None],
    ) -> None:
        self._configure_runtime = configure_runtime
        self._warmup = warmup
        self._stop_runtime = stop_runtime
        self._lock = threading.Lock()
        self._ready = False
        self._process: Any | None = None

    def ensure_ready(self) -> None:
        with self._lock:
            if self._ready:
                return
            self._process = self._configure_runtime()
            self._warmup()
            self._ready = True

    def shutdown(self) -> None:
        with self._lock:
            if self._process is not None:
                self._stop_runtime(self._process)
                self._process = None
            self._ready = False
