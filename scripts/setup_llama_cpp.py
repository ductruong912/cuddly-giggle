from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import Settings, settings  # noqa: E402
from app.services.llama_bootstrap import (  # noqa: E402
    LlamaBootstrapConfig,
    LlamaBootstrapResult,
    bootstrap_llama_cpp,
    is_llama_cpp_ready,
    resolve_latest_llama_cpp_release_urls,
)


def main(
    *,
    app_settings: Settings = settings,
    bootstrap=bootstrap_llama_cpp,
    resolve_release_urls=resolve_latest_llama_cpp_release_urls,
) -> LlamaBootstrapResult:
    llama_dir = Path(app_settings.llama_cpp_dir).resolve()
    release_url = app_settings.llama_cpp_release_url
    release_urls: tuple[str, ...] = ()
    if not release_url and not is_llama_cpp_ready(llama_dir):
        release_urls = tuple(resolve_release_urls(flavor=app_settings.llama_cpp_release_flavor))

    result = bootstrap(
        config=LlamaBootstrapConfig(
            llama_dir=llama_dir,
            models_dir=Path(app_settings.llama_cpp_models_dir).resolve(),
            llama_release_url=release_url,
            llama_release_urls=release_urls,
        )
    )
    return result


def _print_result(result: LlamaBootstrapResult) -> None:
    print(f"llama.cpp: {'downloaded' if result.downloaded_llama_cpp else 'ready'}")
    if result.downloaded_models:
        print("models downloaded:")
        for name in result.downloaded_models:
            print(f"- {name}")
    else:
        print("models: ready")
    print(f"llama dir: {result.llama_dir}")
    print(f"models dir: {result.models_dir}")


if __name__ == "__main__":
    _print_result(main())
