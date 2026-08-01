"""The CI subset must pin the same versions as the full requirements file.

If they drift, CI silently stops testing what production runs — the kind of gap
that only surfaces in production.
"""
from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
FULL = REPO_ROOT / "requirements.txt"
CI = REPO_ROOT / "requirements-ci.txt"


def read_requirements(path: Path) -> dict[str, str]:
    """Map distribution name to its full specifier, ignoring comments and flags."""
    entries: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        name = line.split("==")[0].split(">=")[0].split("[")[0].strip()
        entries[name.lower()] = line
    return entries


@pytest.fixture(scope="module")
def full_requirements() -> dict[str, str]:
    return read_requirements(FULL)


@pytest.fixture(scope="module")
def ci_requirements() -> dict[str, str]:
    return read_requirements(CI)


def test_both_files_exist() -> None:
    assert FULL.is_file() and CI.is_file()


def test_the_ci_subset_is_a_subset(
    ci_requirements: dict, full_requirements: dict
) -> None:
    unknown = set(ci_requirements) - set(full_requirements)

    assert not unknown, f"requirements-ci.txt pins packages absent from requirements.txt: {unknown}"


def test_the_pins_match(ci_requirements: dict, full_requirements: dict) -> None:
    drifted = {
        name: (specifier, full_requirements[name])
        for name, specifier in ci_requirements.items()
        if specifier != full_requirements[name]
    }

    assert not drifted, f"pins differ between requirements files: {drifted}"


def test_the_suites_own_dependencies_are_pinned(ci_requirements: dict) -> None:
    """Whatever the tests import directly has to be installable in CI."""
    for required in ("pytest", "httpx", "fastapi", "pydantic", "pymupdf"):
        assert required in ci_requirements, f"{required} is missing from requirements-ci.txt"


def test_the_heavy_extras_are_excluded(ci_requirements: dict) -> None:
    """Pulling these into CI would need CUDA and a custom index."""
    for excluded in ("paddlepaddle-gpu", "paddleocr", "paddlex", "onnxruntime"):
        assert excluded not in ci_requirements
