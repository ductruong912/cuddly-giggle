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
    parser.add_argument(
        "--cuda",
        help="Pass a CUDA variant to pip when installing dependencies (for example: cu126).",
    )
    return parser


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if platform.system() != "Windows":
        parser.error("setup_runtime.py supports Windows only")
    if args.check and any(getattr(args, name.replace("-", "_")) for name in SETUP_STEPS):
        parser.error("--check cannot be combined with setup flags")
    if args.cuda is not None and not (args.dependencies or args.all):
        parser.error("--cuda requires --dependencies or --all")
    return args


def selected_steps(args: argparse.Namespace) -> list[str]:
    if args.check:
        return [CHECK_STEP]
    if args.all:
        return list(SETUP_STEPS)
    return [name for name in SETUP_STEPS if getattr(args, name.replace("-", "_"))]


def run_steps(
    step_names: Sequence[str],
    runners: Mapping[str, Callable[[], object]],
) -> list[StepResult]:
    results: list[StepResult] = []
    for name in step_names:
        try:
            outcome = runners[name]()
        except Exception as exc:
            results.append(StepResult(name, False, str(exc)))
        else:
            message = str(outcome) if outcome is not None else "completed"
            results.append(StepResult(name, True, message))
    return results


def install_dependencies(cuda: str | None = None) -> None:
    """Install project dependencies with the interpreter running this command."""
    if platform.system() == "Windows" and sys.prefix == sys.base_prefix:
        raise RuntimeError(
            "Dependency installation must run from the project's virtual environment. "
            "Activate venv or run venv\\Scripts\\python.exe scripts\\setup_runtime.py --dependencies."
        )
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "-r",
        str(REPO_ROOT / "requirements.txt"),
    ]
    if cuda:
        command.append(f"--config-settings=--cuda={cuda}")
    subprocess.run(command, check=True)


def warmup_ocr_models(
    app_settings: object | None = None,
    engine_factory: Callable[[str, object], object] | None = None,
) -> None:
    """Warm the configured primary and fallback OCR engine pipelines.

    The optional arguments keep this adapter independent from concrete OCR
    runtimes during tests while the normal CLI path uses the app's registry.
    """
    if app_settings is None:
        from app.core.config import settings

        app_settings = settings
    if engine_factory is None:
        from app.engines.registry import create_engine

        engine_factory = create_engine

    warmed_names: set[str] = set()
    for engine_name in (
        getattr(app_settings, "primary_engine"),
        getattr(app_settings, "fallback_engine"),
    ):
        normalized_name = (engine_name or "").strip().lower()
        if normalized_name in warmed_names:
            continue
        warmed_names.add(normalized_name)

        engine = engine_factory(engine_name, app_settings)
        warmup = getattr(engine, "warmup", None)
        if not callable(warmup):
            raise RuntimeError(
                f"Configured OCR engine {engine_name!r} does not support warmup."
            )
        warmup()


def prepare_llama() -> object:
    """Delegate llama.cpp and GGUF setup to the existing bootstrap script."""
    from scripts.setup_llama_cpp import main as setup_llama

    return setup_llama()


def run_preflight() -> None:
    """Run the existing read-only runtime diagnostic."""
    from scripts.preflight_runtime import main as preflight

    preflight()


def _default_runners(cuda: str | None) -> dict[str, Callable[[], object]]:
    return {
        "dependencies": lambda: install_dependencies(cuda=cuda),
        "ocr-models": warmup_ocr_models,
        "llama": prepare_llama,
        CHECK_STEP: run_preflight,
    }


def _retry_command(step_name: str, cuda: str | None) -> str:
    command = [sys.executable, str(Path(__file__).resolve()), f"--{step_name}"]
    if step_name == "dependencies" and cuda:
        command.extend(["--cuda", cuda])
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
        else _default_runners(args.cuda)
    )
    results = run_steps(step_names, active_runners)
    for result in results:
        status = "OK" if result.ok else "FAILED"
        print(f"[{status}] {result.name}: {result.message}")
        if not result.ok:
            print(f"Retry: {_retry_command(result.name, args.cuda)}")
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
