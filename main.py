from __future__ import annotations

import os
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message="No ccache found")

# pyrefly: ignore [missing-import]
import uvicorn

from api.routes import get_fast_orchestrator, get_orchestrator
from api.application import app
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
from services.vl_runtime import VLRuntimeManager


def bootstrap_llama_cpp_on_startup(
    *,
    app_settings: Settings = settings,
    bootstrap=bootstrap_llama_cpp,
    resolve_release_urls=resolve_latest_llama_cpp_release_urls,
) -> None:
    if not app_settings.auto_download_llama_cpp:
        return

    llama_dir = Path(app_settings.llama_cpp_dir).resolve()
    release_url = app_settings.llama_cpp_release_url
    release_urls: tuple[str, ...] = ()
    if not release_url and not is_llama_cpp_ready(llama_dir):
        release_urls = tuple(resolve_release_urls(flavor=app_settings.llama_cpp_release_flavor))

    bootstrap(
        config=LlamaBootstrapConfig(
            llama_dir=llama_dir,
            models_dir=Path(app_settings.llama_cpp_models_dir).resolve(),
            llama_release_url=release_url,
            llama_release_urls=release_urls,
        )
    )


def configure_gguf_runtime_on_startup(
    *,
    app_settings: Settings = settings,
    bootstrap=bootstrap_llama_cpp,
    resolve_release_urls=resolve_latest_llama_cpp_release_urls,
    start_server=start_llama_server_if_needed,
):
    if not app_settings.paddleocr_vl_use_gguf:
        return None

    # Only bootstrap/own a local llama.cpp runtime when we are autostarting it. When
    # pointed at an external server (e.g. a separate llama container), skip both the
    # binary download and startup â€” the app just talks to PADDLEOCR_VL_REC_SERVER_URL.
    if not app_settings.llama_server_autostart:
        return None

    llama_dir = Path(app_settings.llama_cpp_dir).resolve()
    models_dir = Path(app_settings.llama_cpp_models_dir).resolve()
    return start_server(
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


def warmup_models_on_startup() -> None:
    if not settings.warmup_models_on_startup:
        return
    primary_engine = get_orchestrator().primary_engine
    warmup = getattr(primary_engine, "warmup", None)
    if not callable(warmup):
        raise RuntimeError(f"Primary engine {primary_engine.__class__.__name__} does not support warmup.")
    warmup()


def warmup_fast_ocr_on_startup(
    *,
    app_settings: Settings = settings,
    orchestrator_factory=get_fast_orchestrator,
) -> None:
    if not app_settings.warmup_models_on_startup:
        return
    orchestrator = orchestrator_factory()
    warmup_orchestrator = getattr(orchestrator, "warmup", None)
    if callable(warmup_orchestrator):
        warmup_orchestrator()
        return
    engine = orchestrator.engine
    warmup = getattr(engine, "warmup", None)
    if not callable(warmup):
        raise RuntimeError(
            f"Fast OCR engine {engine.__class__.__name__} does not support warmup."
        )
    warmup()


def silence_known_warnings() -> None:
    warnings.filterwarnings("ignore", message=r"'llama-cpp-server' does not support")


def main() -> None:
    silence_known_warnings()
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    warmup_fast_ocr_on_startup()
    runtime_manager = VLRuntimeManager(
        configure_runtime=configure_gguf_runtime_on_startup,
        warmup=warmup_models_on_startup,
        stop_runtime=stop_llama_server,
    )
    app.state.vl_runtime_manager = runtime_manager
    try:
        uvicorn.run(app, host=host, port=port, reload=False)
    finally:
        runtime_manager.shutdown()


if __name__ == "__main__":
    main()
