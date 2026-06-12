from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import socket
import subprocess
import time
from typing import Callable, Protocol


logger = logging.getLogger("app")


class ProcessLike(Protocol):
    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...
    def kill(self) -> None: ...


@dataclass(frozen=True)
class LlamaServerConfig:
    executable_path: Path = field(default_factory=lambda: Path.cwd() / "llama" / "llama-server.exe")
    model_path: Path = field(default_factory=lambda: Path.cwd() / "models" / "PaddleOCR-VL-1.6-GGUF.gguf")
    mmproj_path: Path = field(default_factory=lambda: Path.cwd() / "models" / "PaddleOCR-VL-1.6-GGUF-mmproj.gguf")
    host: str = "127.0.0.1"
    port: int = 8080
    ctx_size: int = 4096
    parallel: int = 1
    n_gpu_layers: int = 40
    mmproj_offload: bool = True
    flash_attn: str = "on"
    threads: int = 4
    threads_batch: int = 4
    temp: float = 0.0
    startup_timeout_seconds: float = 120.0


def build_llama_server_command(config: LlamaServerConfig) -> list[str]:
    command = [
        str(config.executable_path),
        "-m",
        str(config.model_path),
        "--mmproj",
        str(config.mmproj_path),
        "--host",
        config.host,
        "--port",
        str(config.port),
        "--ctx-size",
        str(config.ctx_size),
        "--parallel",
        str(config.parallel),
        "--n-gpu-layers",
        str(config.n_gpu_layers),
    ]
    if config.mmproj_offload:
        command.append("--mmproj-offload")
    command.extend(
        [
            "--flash-attn",
            config.flash_attn,
            "--threads",
            str(config.threads),
            "--threads-batch",
            str(config.threads_batch),
            "--temp",
            _format_float(config.temp),
        ]
    )
    return command


def is_tcp_port_open(host: str, port: int, timeout_seconds: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def wait_for_tcp_port(host: str, port: int, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if is_tcp_port_open(host, port):
            return True
        time.sleep(0.25)
    return False


def start_llama_server_if_needed(
    config: LlamaServerConfig,
    *,
    port_check: Callable[[str, int], bool] = is_tcp_port_open,
    popen: Callable[..., ProcessLike] = subprocess.Popen,
    wait_for_server: Callable[[str, int, float], bool] = wait_for_tcp_port,
) -> ProcessLike | None:
    if port_check(config.host, config.port):
        logger.info("llama.cpp server already listening on %s:%s", config.host, config.port)
        return None

    _validate_paths(config)
    command = build_llama_server_command(config)
    logger.info("Starting llama.cpp server: %s", " ".join(command))
    process = popen(command, cwd=str(config.executable_path.parent))
    if wait_for_server(config.host, config.port, config.startup_timeout_seconds):
        return process

    stop_llama_server(process)
    raise RuntimeError(
        f"llama.cpp server did not become ready on {config.host}:{config.port} "
        f"within {config.startup_timeout_seconds:g}s."
    )


def stop_llama_server(process: ProcessLike | None, timeout_seconds: float = 10.0) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except Exception:
        process.kill()
        process.wait(timeout=timeout_seconds)


def _validate_paths(config: LlamaServerConfig) -> None:
    missing = [
        path
        for path in [config.executable_path, config.model_path, config.mmproj_path]
        if not path.is_file()
    ]
    if missing:
        raise RuntimeError("Missing llama.cpp runtime file(s): " + ", ".join(str(path) for path in missing))


def _format_float(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return str(value)
