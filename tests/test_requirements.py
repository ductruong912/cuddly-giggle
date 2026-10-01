"""Application and test dependencies share one requirements file."""
from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_requirements() -> dict[str, str]:
    """Map distribution names to their declared dependency specifiers."""
    entries: dict[str, str] = {}
    for line in (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = line.split("==")[0].split(">=")[0].split("[")[0].strip().lower()
        assert name not in entries, f"Duplicate dependency: {name}"
        entries[name] = line
    return entries


def test_application_and_test_dependencies_are_declared() -> None:
    dependencies = read_requirements()
    required = {"fastapi", "uvicorn", "pydantic", "python-multipart", "python-dotenv",
                "slowapi", "openai", "httpx", "pymupdf", "psycopg", "psycopg-pool",
                "paddleocr", "paddlex", "onnxruntime", "numpy", "opencv-contrib-python", "pytest"}
    assert required <= dependencies.keys()


def test_paddle_variant_is_installed_separately() -> None:
    dependencies = read_requirements()
    assert "paddlepaddle" not in dependencies
    assert "paddlepaddle-gpu" not in dependencies
