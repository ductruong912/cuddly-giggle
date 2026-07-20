"""llama.cpp runtime: bootstrap (download binaries + models) and server control."""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
from typing import Callable, Protocol
import zipfile

import httpx


logger = logging.getLogger("app")


# =====================================================================================
# Bootstrap: download llama.cpp binaries and model artifacts
# =====================================================================================

HF_GGUF_REPO = "https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF/resolve/main"
LLAMA_CPP_LATEST_RELEASE_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
DEFAULT_LLAMA_CPP_FLAVOR = "win-cuda-12.4-x64"
DEFAULT_MODEL_BYTES = 800 * 1024 * 1024
DEFAULT_HTTP_TIMEOUT_SECONDS = 60.0

REQUIRED_LLAMA_FILES = (
    "llama-server.exe",
    "llama.dll",
    "llama-common.dll",
    "ggml.dll",
    "ggml-base.dll",
)


@dataclass(frozen=True)
class DownloadArtifact:
    url: str
    path: Path
    min_bytes: int = 1


@dataclass(frozen=True)
class LlamaBootstrapConfig:
    llama_dir: Path = field(default_factory=lambda: Path.cwd() / "llama")
    models_dir: Path = field(default_factory=lambda: Path.cwd() / "models")
    llama_release_url: str = ""
    llama_release_urls: tuple[str, ...] = ()
    min_model_bytes: int = DEFAULT_MODEL_BYTES
    timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS


@dataclass(frozen=True)
class LlamaBootstrapResult:
    downloaded_llama_cpp: bool
    downloaded_models: list[str]
    llama_dir: Path
    models_dir: Path


class HttpDownloader:
    def __init__(self, timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS, attempts: int = 3) -> None:
        self.timeout_seconds = timeout_seconds
        self.attempts = max(1, attempts)

    def download_file(self, url: str, destination: Path) -> None:
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            try:
                self._download_file_once(url, destination)
                return
            except (OSError, httpx.HTTPError) as exc:
                last_error = exc
                if attempt + 1 < self.attempts:
                    logger.warning("Download attempt %s/%s failed for %s: %s", attempt + 1, self.attempts, url, exc)
        assert last_error is not None
        raise last_error

    def _download_file_once(self, url: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                tmp_path = Path(tmp.name)
                with httpx.stream("GET", url, follow_redirects=True, timeout=self.timeout_seconds) as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        tmp.write(chunk)
                tmp.flush()
            os.replace(tmp_path, destination)
        except Exception:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
            raise

    def download_and_extract_zip(self, url: str, destination_dir: Path) -> None:
        destination_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=destination_dir.parent) as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            archive_path = tmp_dir / "llama.cpp.zip"
            extract_dir = tmp_dir / "extract"
            extract_dir.mkdir()
            self.download_file(url, archive_path)
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(extract_dir)
            _install_extracted_files(extract_dir, destination_dir, tmp_dir)

    def get_json(self, url: str) -> dict[str, object]:
        response = httpx.get(url, follow_redirects=True, timeout=self.timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Expected JSON object from {url}")
        return payload


def default_model_artifacts(models_dir: Path, min_bytes: int = DEFAULT_MODEL_BYTES) -> list[DownloadArtifact]:
    filenames = [
        "PaddleOCR-VL-1.6-GGUF.gguf",
        "PaddleOCR-VL-1.6-GGUF-mmproj.gguf",
    ]
    return [
        DownloadArtifact(
            url=f"{HF_GGUF_REPO}/{filename}",
            path=models_dir / filename,
            min_bytes=min_bytes,
        )
        for filename in filenames
    ]


def is_artifact_ready(path: Path, min_bytes: int = 1) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= min_bytes
    except OSError:
        return False


def is_llama_cpp_ready(llama_dir: Path) -> bool:
    return all(is_artifact_ready(llama_dir / name) for name in REQUIRED_LLAMA_FILES)


def select_llama_cpp_release_urls(
    release_payload: dict[str, object],
    *,
    flavor: str = DEFAULT_LLAMA_CPP_FLAVOR,
) -> list[str]:
    assets = release_payload.get("assets")
    if not isinstance(assets, list):
        raise RuntimeError("GitHub release payload does not contain an assets list.")

    binary_suffix = f"-bin-{flavor}.zip"
    runtime_suffix = _cuda_runtime_suffix(flavor)
    binary_url = ""
    runtime_url = ""

    for item in assets:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        url = item.get("browser_download_url")
        if not isinstance(name, str) or not isinstance(url, str):
            continue
        if name.startswith("llama-") and name.endswith(binary_suffix):
            binary_url = url
        elif runtime_suffix and name == runtime_suffix:
            runtime_url = url

    if not binary_url:
        raise RuntimeError(f"Could not find llama.cpp release asset for flavor {flavor!r}.")
    if runtime_suffix and not runtime_url:
        raise RuntimeError(f"Could not find llama.cpp CUDA runtime asset {runtime_suffix!r}.")

    urls = [binary_url]
    if runtime_url:
        urls.append(runtime_url)
    return urls


def resolve_latest_llama_cpp_release_urls(
    *,
    flavor: str = DEFAULT_LLAMA_CPP_FLAVOR,
    downloader: HttpDownloader | None = None,
) -> list[str]:
    downloader = downloader or HttpDownloader()
    payload = downloader.get_json(LLAMA_CPP_LATEST_RELEASE_API)
    return select_llama_cpp_release_urls(payload, flavor=flavor)


def bootstrap_llama_cpp(
    *,
    config: LlamaBootstrapConfig | None = None,
    downloader: HttpDownloader | None = None,
) -> LlamaBootstrapResult:
    config = config or LlamaBootstrapConfig()
    downloader = downloader or HttpDownloader(timeout_seconds=config.timeout_seconds)

    downloaded_llama_cpp = False
    if not is_llama_cpp_ready(config.llama_dir):
        release_urls = _configured_release_urls(config)
        if not release_urls:
            raise RuntimeError(
                "llama.cpp is missing and LLAMA_CPP_RELEASE_URL is not configured. "
                "Set LLAMA_CPP_RELEASE_URL to a Windows llama.cpp release zip."
            )
        for release_url in release_urls:
            logger.info("Downloading llama.cpp from %s", release_url)
            downloader.download_and_extract_zip(release_url, config.llama_dir)
        downloaded_llama_cpp = True
        if not is_llama_cpp_ready(config.llama_dir):
            missing = [name for name in REQUIRED_LLAMA_FILES if not (config.llama_dir / name).is_file()]
            raise RuntimeError(f"llama.cpp archive did not provide required files: {', '.join(missing)}")

    downloaded_models: list[str] = []
    for artifact in default_model_artifacts(config.models_dir, min_bytes=config.min_model_bytes):
        if is_artifact_ready(artifact.path, artifact.min_bytes):
            continue
        logger.info("Downloading model artifact %s", artifact.path.name)
        downloader.download_file(artifact.url, artifact.path)
        if not is_artifact_ready(artifact.path, artifact.min_bytes):
            raise RuntimeError(f"Downloaded model {artifact.path.name} is too small or incomplete.")
        downloaded_models.append(artifact.path.name)

    return LlamaBootstrapResult(
        downloaded_llama_cpp=downloaded_llama_cpp,
        downloaded_models=downloaded_models,
        llama_dir=config.llama_dir,
        models_dir=config.models_dir,
    )


def _install_extracted_files(source_dir: Path, destination_dir: Path, staging_root: Path) -> None:
    missing = [name for name in REQUIRED_LLAMA_FILES if not any(path.name == name for path in source_dir.rglob(name))]
    if missing:
        raise RuntimeError(f"llama.cpp archive did not provide required files: {', '.join(missing)}")
    staged_dir = staging_root / "installed"
    if destination_dir.exists():
        shutil.copytree(destination_dir, staged_dir)
    else:
        staged_dir.mkdir()
    for path in source_dir.rglob("*"):
        if not path.is_file():
            continue
        target = staged_dir / path.name
        shutil.copy2(path, target)
    backup_dir = staging_root / "previous"
    if destination_dir.exists():
        os.replace(destination_dir, backup_dir)
    try:
        os.replace(staged_dir, destination_dir)
    except Exception:
        if backup_dir.exists():
            os.replace(backup_dir, destination_dir)
        raise
    shutil.rmtree(backup_dir, ignore_errors=True)


def _configured_release_urls(config: LlamaBootstrapConfig) -> list[str]:
    urls = [url.strip() for url in config.llama_release_urls if url.strip()]
    if urls:
        return urls
    raw = config.llama_release_url.strip()
    if not raw:
        return []
    return [url.strip() for url in raw.replace(",", ";").split(";") if url.strip()]


def _cuda_runtime_suffix(flavor: str) -> str:
    if "win-cuda-" not in flavor:
        return ""
    return f"cudart-llama-bin-{flavor}.zip"


# =====================================================================================
# Server: build command, health-check ports, start/stop the llama-server process
# =====================================================================================

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
    log_verbosity: int = 1
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
            "-lv",
            str(config.log_verbosity),
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
