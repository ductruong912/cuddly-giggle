from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from app.api.dependencies import get_orchestrator
from app.application import app
from app.core.config import Settings, settings
from app.services.runtime.llama_bootstrap import (
    LlamaBootstrapConfig,
    bootstrap_llama_cpp,
    is_llama_cpp_ready,
    resolve_latest_llama_cpp_release_urls,
)
from app.services.runtime.llama_server import (
    LlamaServerConfig,
    start_llama_server_if_needed,
    stop_llama_server,
)


def bootstrap_llama_cpp_on_startup(
    *,
    app_settings: Settings = settings,
    bootstrap=bootstrap_llama_cpp,
    resolve_release_urls=resolve_latest_llama_cpp_release_urls,
) -> None:
    if not app_settings.auto_download_llama_cpp and not app_settings.paddleocr_vl_use_gguf:
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

    bootstrap_llama_cpp_on_startup(
        app_settings=app_settings,
        bootstrap=bootstrap,
        resolve_release_urls=resolve_release_urls,
    )
    if not app_settings.llama_server_autostart:
        return None

    llama_dir = Path(app_settings.llama_cpp_dir).resolve()
    models_dir = Path(app_settings.llama_cpp_models_dir).resolve()
    return start_server(
        LlamaServerConfig(
            executable_path=llama_dir / "llama-server.exe",
            model_path=models_dir / "PaddleOCR-VL-1.6-GGUF.gguf",
            mmproj_path=models_dir / "PaddleOCR-VL-1.6-GGUF-mmproj.gguf",
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


def main() -> None:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    llama_process = configure_gguf_runtime_on_startup()
    try:
        warmup_models_on_startup()
        uvicorn.run(app, host=host, port=port, reload=False)
    finally:
        stop_llama_server(llama_process)


if __name__ == "__main__":
    main()
