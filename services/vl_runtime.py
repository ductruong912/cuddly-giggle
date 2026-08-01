"""Lifecycle for the optional PaddleOCR-VL (llama.cpp GGUF) runtime."""
from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path
import threading
from typing import Any

from config.config import Settings, settings
from services.llama import (
    LlamaBootstrapConfig,
    LlamaServerConfig,
    bootstrap_llama_cpp,
    is_llama_cpp_ready,
    resolve_latest_llama_cpp_release_urls,
    start_llama_server_if_needed,
    stop_llama_server,
)


logger = logging.getLogger(__name__)


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

    @property
    def is_ready(self) -> bool:
        return self._ready

    def ensure_ready(self) -> None:
        """Start the runtime and warm the models; concurrent callers wait for the first."""
        with self._lock:
            if self._ready:
                return
            self._process = self._configure_runtime()
            self._warmup()
            self._ready = True

    def shutdown(self) -> None:
        """Stop a runtime this process started. Safe to call when nothing was started."""
        with self._lock:
            if self._process is not None:
                self._stop_runtime(self._process)
                self._process = None
            self._ready = False


def build_vl_runtime_manager(
    *,
    warmup: Callable[[], None],
    app_settings: Settings = settings,
) -> VLRuntimeManager:
    """Wire the manager to the configured llama.cpp bootstrap and server startup."""
    return VLRuntimeManager(
        configure_runtime=lambda: _configure_gguf_runtime(app_settings),
        warmup=warmup,
        stop_runtime=stop_llama_server,
    )


def _configure_gguf_runtime(app_settings: Settings) -> Any | None:
    """Download llama.cpp if configured to, then start the local server when we own it."""
    if not app_settings.paddleocr_vl_use_gguf:
        return None

    # Pointed at an external server (e.g. the llama container in docker-compose):
    # neither download nor start anything, just talk to PADDLEOCR_VL_REC_SERVER_URL.
    if not app_settings.llama_server_autostart:
        return None

    llama_dir = Path(app_settings.llama_cpp_dir).resolve()
    models_dir = Path(app_settings.llama_cpp_models_dir).resolve()
    _bootstrap_llama_cpp_if_enabled(app_settings, llama_dir, models_dir)
    return start_llama_server_if_needed(
        LlamaServerConfig(
            executable_path=llama_dir / "llama-server.exe",
            model_path=models_dir / app_settings.llama_cpp_model_file,
            mmproj_path=models_dir / app_settings.llama_cpp_mmproj_file,
            host=app_settings.llama_server_host,
            port=app_settings.llama_server_port,
            ctx_size=app_settings.llama_server_ctx_size,
            parallel=app_settings.llama_server_parallel,
            n_gpu_layers=app_settings.llama_server_n_gpu_layers,
            mmproj_offload=app_settings.llama_server_mmproj_offload,
            flash_attn=app_settings.llama_server_flash_attn,
            threads=app_settings.llama_server_threads,
            threads_batch=app_settings.llama_server_threads_batch,
            temp=app_settings.llama_server_temp,
            log_verbosity=app_settings.llama_server_log_verbosity,
            startup_timeout_seconds=app_settings.llama_server_startup_timeout_seconds,
        )
    )


def _bootstrap_llama_cpp_if_enabled(
    app_settings: Settings,
    llama_dir: Path,
    models_dir: Path,
) -> None:
    """Fetch the llama.cpp binaries and GGUF weights when AUTO_DOWNLOAD_LLAMA_CPP is on."""
    if not app_settings.auto_download_llama_cpp:
        return

    release_url = app_settings.llama_cpp_release_url
    release_urls: tuple[str, ...] = ()
    if not release_url and not is_llama_cpp_ready(llama_dir):
        release_urls = tuple(
            resolve_latest_llama_cpp_release_urls(flavor=app_settings.llama_cpp_release_flavor)
        )

    logger.info("checking llama.cpp runtime assets in %s", llama_dir)
    bootstrap_llama_cpp(
        config=LlamaBootstrapConfig(
            llama_dir=llama_dir,
            models_dir=models_dir,
            llama_release_url=release_url,
            llama_release_urls=release_urls,
        )
    )
