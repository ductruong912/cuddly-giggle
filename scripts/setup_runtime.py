"""Orchestrate the optional Windows runtime setup steps.

The concrete installers are deliberately injected so this command can be tested
without downloading models or requiring a GPU.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import platform
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass


SETUP_STEPS = ("dependencies", "ocr-models", "llama")
CHECK_STEP = "check"
PRODUCT_NAME = "Cuddly Giggle OCR"
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@dataclass(frozen=True)
class StepResult:
    name: str
    ok: bool
    message: str


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run manual Windows runtime setup steps.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Check the configured runtime.")
    mode.add_argument("--all", action="store_true", help="Run all setup steps.")
    parser.add_argument("--dependencies", action="store_true", help="Install Python dependencies.")
    parser.add_argument("--ocr-models", action="store_true", help="Download OCR models.")
    parser.add_argument("--llama", action="store_true", help="Set up the Llama runtime.")
    parser.add_argument("--cuda", help=argparse.SUPPRESS)
    return parser


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if platform.system() != "Windows":
        parser.error("setup_runtime.py supports Windows only")
    if args.check and any(getattr(args, name.replace("-", "_")) for name in SETUP_STEPS):
        parser.error("--check cannot be combined with setup flags")
    if args.cuda is not None:
        parser.error("--cuda is no longer supported; install the Paddle CUDA wheel separately.")
    return args


def selected_steps(args: argparse.Namespace) -> list[str]:
    if args.check:
        return [CHECK_STEP]
    if args.all:
        from services.local_ocr_selector import has_usable_gpu

        return list(SETUP_STEPS if has_usable_gpu() else SETUP_STEPS[:2])
    return [name for name in SETUP_STEPS if getattr(args, name.replace("-", "_"))]


def run_steps(
    step_names: Sequence[str],
    runners: Mapping[str, Callable[[], object]],
    *,
    stop_on_failure: bool = False,
) -> list[StepResult]:
    results: list[StepResult] = []
    for name in step_names:
        try:
            outcome = runners[name]()
        except Exception as exc:
            results.append(StepResult(name, False, str(exc)))
            if stop_on_failure:
                break
        else:
            message = str(outcome) if outcome is not None else "completed"
            results.append(StepResult(name, True, message))
    return results


def install_dependencies() -> None:
    """Install project dependencies with the interpreter running this command."""
    if platform.system() == "Windows" and sys.prefix == sys.base_prefix:
        raise RuntimeError(
            "Dependency installation must run from the project's virtual environment. "
            "Activate venv or run venv\\Scripts\\python.exe scripts\\setup_runtime.py --dependencies."
        )
    from services.local_ocr_selector import has_usable_gpu

    gpu = has_usable_gpu()
    paddle_package = "paddlepaddle-gpu==3.3.0" if gpu else "paddlepaddle==3.3.0"
    paddle_index = "cu126" if gpu else "cpu"
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install", paddle_package,
            "-i", f"https://www.paddlepaddle.org.cn/packages/stable/{paddle_index}/",
        ],
        check=True,
    )
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "-r",
        str(REPO_ROOT / "requirements.txt"),
    ]
    subprocess.run(command, check=True)


def warmup_ocr_models() -> None:
    """Use the same explicit model setup command for CPU and GPU machines."""
    from config.config import settings
    from scripts.setup_models import main as setup_models

    setup_models(["--auto"])
    model_root = Path(settings.paddlex_cache_home) / "official_models"
    if not model_root.is_dir() or not any(model_root.iterdir()):
        raise RuntimeError("OCR model cache is empty after warmup; retry --ocr-models.")


def prepare_llama() -> object:
    """Delegate llama.cpp and GGUF setup to the existing bootstrap script."""
    from scripts.setup_llama_cpp import main as setup_llama

    return setup_llama()


def run_preflight() -> None:
    """Run the existing read-only runtime diagnostic."""
    from scripts.preflight_runtime import main as preflight

    result = preflight()
    if result not in (None, 0):
        raise RuntimeError("Runtime check failed; run --check to see missing components.")


def _default_runners() -> dict[str, Callable[[], object]]:
    return {
        "dependencies": install_dependencies,
        "ocr-models": warmup_ocr_models,
        "llama": prepare_llama,
        CHECK_STEP: run_preflight,
    }


def _retry_command(step_name: str) -> str:
    command = [sys.executable, str(Path(__file__).resolve()), f"--{step_name}"]
    return subprocess.list2cmdline(command)


def main(
    argv: Sequence[str] | None = None,
    runners: Mapping[str, Callable[[], object]] | None = None,
) -> int:
    args = parse_args(argv)
    step_names = selected_steps(args)
    if not step_names:
        _build_parser().print_help(sys.stderr)
        return 2

    active_runners = (
        runners
        if runners is not None
        else _default_runners()
    )
    results = run_steps(step_names, active_runners, stop_on_failure=args.all)
    for result in results:
        status = "OK" if result.ok else "FAILED"
        print(f"{PRODUCT_NAME} [{status}] {result.name}: {result.message}")
        if not result.ok:
            print(f"Retry: {_retry_command(result.name)}")
    if len(results) < len(step_names):
        skipped = ", ".join(step_names[len(results):])
        print(f"{PRODUCT_NAME} [SKIPPED] {skipped}: a prerequisite step failed.")
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
