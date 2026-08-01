"""llama.cpp runtime: bootstrap (download binaries + models) and server control."""
from __future__ import annotations

from services.llama.bootstrap import (
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    DEFAULT_LLAMA_CPP_FLAVOR,
    DEFAULT_MODEL_BYTES,
    HF_GGUF_REPO,
    LLAMA_CPP_LATEST_RELEASE_API,
    REQUIRED_LLAMA_FILES,
    DownloadArtifact,
    HttpDownloader,
    LlamaBootstrapConfig,
    LlamaBootstrapResult,
    bootstrap_llama_cpp,
    default_model_artifacts,
    is_artifact_ready,
    is_llama_cpp_ready,
    resolve_latest_llama_cpp_release_urls,
    select_llama_cpp_release_urls,
)
from services.llama.server import (
    LlamaServerConfig,
    ProcessLike,
    build_llama_server_command,
    is_tcp_port_open,
    start_llama_server_if_needed,
    stop_llama_server,
    wait_for_tcp_port,
)


__all__ = [
    "DEFAULT_HTTP_TIMEOUT_SECONDS",
    "DEFAULT_LLAMA_CPP_FLAVOR",
    "DEFAULT_MODEL_BYTES",
    "DownloadArtifact",
    "HF_GGUF_REPO",
    "HttpDownloader",
    "LLAMA_CPP_LATEST_RELEASE_API",
    "LlamaBootstrapConfig",
    "LlamaBootstrapResult",
    "LlamaServerConfig",
    "ProcessLike",
    "REQUIRED_LLAMA_FILES",
    "bootstrap_llama_cpp",
    "build_llama_server_command",
    "default_model_artifacts",
    "is_artifact_ready",
    "is_llama_cpp_ready",
    "is_tcp_port_open",
    "resolve_latest_llama_cpp_release_urls",
    "select_llama_cpp_release_urls",
    "start_llama_server_if_needed",
    "stop_llama_server",
    "wait_for_tcp_port",
]
