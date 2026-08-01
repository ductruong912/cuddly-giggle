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
    is_tcp_port_open,
    resolve_latest_llama_cpp_release_urls,
    start_llama_server_if_needed,
    stop_llama_server,
)


logger = logging.getLogger(__name__)


class VLRuntimeManager:
    """Own the VL runtime: start it on first use, and notice when it dies.

    ``_ready`` used to latch on forever, so a llama.cpp process that crashed took
    every subsequent request down with it until someone restarted the API. Ready
    is now re-checked against the process and the port on every use.
    """

    def __init__(
        self,
        *,
        configure_runtime: Callable[[], Any | None],
        warmup: Callable[[], None],
        stop_runtime: Callable[[Any], None],
        probe: Callable[[], bool] | None = None,
    ) -> None:
        self._configure_runtime = configure_runtime
        self._warmup = warmup
        self._stop_runtime = stop_runtime
        # Answers "is the backend reachable?" for a server this process does not
        # own — the docker-compose llama container, for instance.
        self._probe = probe
        self._lock = threading.Lock()
        self._ready = False
        self._started = False
        self._process: Any | None = None

    @property
    def is_ready(self) -> bool:
        """True when the runtime was prepared and still looks alive."""
        return self._ready and self._is_alive()

    @property
    def was_started(self) -> bool:
        """True once the runtime has been prepared, alive or not.

        Lets readiness distinguish "not needed yet" from "started and now down":
        the runtime is prepared on first use, so an untouched one is not a fault.
        """
        return self._started

    def ensure_ready(self) -> None:
        """Start the runtime and warm the models, restarting it if it has died."""
        with self._lock:
            if self._ready and self._is_alive():
                return
            if self._ready:
                logger.warning("VL runtime is no longer alive; restarting it")
                self._stop_locked()
            self._process = self._configure_runtime()
            self._warmup()
            self._ready = True
            self._started = True

    def restart(self) -> None:
        """Stop and start the runtime, whatever state it is in.

        A wedged llama.cpp does not exit on its own, and the OCR calls blocked on
        it cannot be cancelled from Python. Killing the process is what makes
        those calls return and hands their stage slots back.
        """
        with self._lock:
            logger.warning("restarting the VL runtime")
            self._stop_locked()
            self._process = self._configure_runtime()
            self._warmup()
            self._ready = True
            self._started = True

    def shutdown(self) -> None:
        """Stop a runtime this process started. Safe to call when nothing was started."""
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self._process is not None:
            self._stop_runtime(self._process)
            self._process = None
        self._ready = False
        self._started = False

    def _is_alive(self) -> bool:
        """Whether the backend is still usable, by process state or by probe."""
        if self._process is not None:
            poll = getattr(self._process, "poll", None)
            if callable(poll) and poll() is not None:
                return False
            return True
        # No owned process: either the runtime is disabled, or an external server
        # is serving the port. The probe distinguishes those.
        return self._probe() if self._probe is not None else True


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
        probe=lambda: _llama_backend_reachable(app_settings),
    )


def _llama_backend_reachable(app_settings: Settings) -> bool:
    """Whether something is listening where the VL backend is expected.

    Used when this process does not own the server — an external llama container,
    or the GGUF path being switched off entirely.
    """
    if not app_settings.paddleocr_vl_use_gguf:
        return True
    return is_tcp_port_open(app_settings.llama_server_host, app_settings.llama_server_port)


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
