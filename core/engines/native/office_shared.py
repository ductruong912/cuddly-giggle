"""Helpers shared by the Word and Excel text engines.

Both formats are Office Open XML zip packages, both need LibreOffice to read
their legacy (.doc / .xls) variants, and both render their tables as Markdown.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess


CONVERSION_TIMEOUT_SECONDS = 60


def find_soffice() -> Path | None:
    """Locate the LibreOffice binary on PATH or in its default Windows install."""
    for executable in ("soffice", "soffice.exe", "libreoffice", "libreoffice.exe"):
        found = shutil.which(executable)
        if found:
            return Path(found)

    for candidate in (
        Path("C:/Program Files/LibreOffice/program/soffice.exe"),
        Path("C:/Program Files (x86)/LibreOffice/program/soffice.exe"),
    ):
        if candidate.exists():
            return candidate
    return None


def convert_office(path: Path, output_dir: Path, *, target_format: str) -> Path:
    """Convert a legacy Office file (.doc/.xls) to its modern format via LibreOffice."""
    source_ext = path.suffix.lower()
    soffice = find_soffice()
    if soffice is None:
        raise RuntimeError(
            f"Legacy {source_ext} requires LibreOffice/soffice for conversion to .{target_format} before parsing."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(soffice),
        "--headless",
        "--convert-to",
        target_format,
        "--outdir",
        str(output_dir),
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=CONVERSION_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Legacy {source_ext} conversion timed out.") from exc
    except OSError as exc:
        raise RuntimeError(f"Legacy {source_ext} conversion could not start: {exc}") from exc
    if completed.returncode != 0:
        detail = _compact_process_output(completed.stderr or completed.stdout)
        raise RuntimeError(f"Legacy {source_ext} conversion failed: {detail}")

    expected_path = output_dir / f"{path.stem}.{target_format}"
    if expected_path.exists():
        return expected_path
    converted = list(output_dir.glob(f"*.{target_format}"))
    if converted:
        return converted[0]
    detail = _compact_process_output(completed.stderr or completed.stdout)
    raise RuntimeError(f"Legacy {source_ext} conversion did not produce a .{target_format} file: {detail}")


def _compact_process_output(message: str, max_len: int = 220) -> str:
    compact = " ".join((message or "").split())
    if len(compact) <= max_len:
        return compact or "no converter output"
    return compact[: max_len - 3] + "..."


def clean_text(text: str) -> str:
    """Collapse runs of whitespace per line and drop blank lines."""
    lines = [" ".join(line.split()) for line in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line).strip()


def rows_to_markdown(rows: list[list[str]]) -> str:
    """Render a rectangular cell grid as a Markdown pipe table."""
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        return ""

    column_count = max(len(row) for row in rows)
    normalized_rows = [pad_row(row, column_count) for row in rows]
    header = normalized_rows[0]
    separator = ["---"] * column_count
    markdown_rows = [_markdown_row(header), _markdown_row(separator)]
    markdown_rows.extend(_markdown_row(row) for row in normalized_rows[1:])
    return "\n".join(markdown_rows)


def _markdown_row(cells: list[str]) -> str:
    return "| " + " | ".join(_escape_markdown_cell(cell) for cell in cells) + " |"


def _escape_markdown_cell(text: str) -> str:
    return clean_text(text).replace("|", r"\|").replace("\n", "<br>")


def pad_row(row: list[str], column_count: int) -> list[str]:
    """Right-pad a row with empty strings so every row has the same width."""
    return row + [""] * max(0, column_count - len(row))
