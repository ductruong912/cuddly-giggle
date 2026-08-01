"""Download the llama.cpp binaries and GGUF weights the VL tier needs."""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import shutil
import tempfile
import zipfile

import httpx


logger = logging.getLogger(__name__)


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
    """Retrying downloader that writes through a temp file so partials never land."""

    def __init__(self, timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS, attempts: int = 3) -> None:
        self.timeout_seconds = timeout_seconds
        self.attempts = max(1, attempts)

    def download_file(self, url: str, destination: Path) -> None:
        """Download ``url`` to ``destination``, retrying transient failures."""
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
        """Download a zip and install its files into ``destination_dir`` atomically."""
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
        """GET ``url`` and return the decoded JSON object."""
        response = httpx.get(url, follow_redirects=True, timeout=self.timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Expected JSON object from {url}")
        return payload


def default_model_artifacts(models_dir: Path, min_bytes: int = DEFAULT_MODEL_BYTES) -> list[DownloadArtifact]:
    """The GGUF weight and projector files the VL recognition tier loads."""
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
    """True when the file exists and is at least ``min_bytes`` long."""
    try:
        return path.is_file() and path.stat().st_size >= min_bytes
    except OSError:
        return False


def is_llama_cpp_ready(llama_dir: Path) -> bool:
    """True when every required llama.cpp binary is present in ``llama_dir``."""
    return all(is_artifact_ready(llama_dir / name) for name in REQUIRED_LLAMA_FILES)


def select_llama_cpp_release_urls(
    release_payload: dict[str, object],
    *,
    flavor: str = DEFAULT_LLAMA_CPP_FLAVOR,
) -> list[str]:
    """Pick the binary (and CUDA runtime) asset URLs for ``flavor`` from a release."""
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
    """Look up the newest llama.cpp release and return its asset URLs for ``flavor``."""
    downloader = downloader or HttpDownloader()
    payload = downloader.get_json(LLAMA_CPP_LATEST_RELEASE_API)
    return select_llama_cpp_release_urls(payload, flavor=flavor)


def bootstrap_llama_cpp(
    *,
    config: LlamaBootstrapConfig | None = None,
    downloader: HttpDownloader | None = None,
) -> LlamaBootstrapResult:
    """Ensure the llama.cpp binaries and GGUF models exist, downloading what is missing."""
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
