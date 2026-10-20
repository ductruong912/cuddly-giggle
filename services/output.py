"""Output helpers: markdown table filtering and parse artifact saving."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import tempfile

from config.config import settings
from core.domain.schemas import ParseResponse


logger = logging.getLogger(__name__)


# =====================================================================================
# Table-only markdown filter
# =====================================================================================

_HTML_TABLE_RE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)
_PIPE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_PIPE_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")


def filter_tables_markdown(markdown: str | None) -> str | None:
    """Return markdown containing only its table blocks, in document order."""
    if not markdown:
        return markdown

    spans: list[tuple[int, str]] = []
    for match in _HTML_TABLE_RE.finditer(markdown):
        spans.append((match.start(), match.group(0).strip()))

    spans.extend(_pipe_table_spans(markdown))

    if not spans:
        return None

    spans.sort(key=lambda span: span[0])
    return "\n\n".join(text for _, text in spans)


def _pipe_table_spans(markdown: str) -> list[tuple[int, str]]:
    spans: list[tuple[int, str]] = []
    block_lines: list[str] = []
    block_start: int | None = None
    offset = 0

    def flush() -> None:
        nonlocal block_lines, block_start
        if block_start is not None and _is_pipe_table(block_lines):
            spans.append((block_start, "".join(block_lines).strip()))
        block_lines = []
        block_start = None

    for line in markdown.splitlines(keepends=True):
        if _PIPE_ROW_RE.match(line):
            if block_start is None:
                block_start = offset
            block_lines.append(line)
        else:
            flush()
        offset += len(line)
    flush()
    return spans


def _is_pipe_table(block_lines: list[str]) -> bool:
    # A real pipe table needs a header, a dash separator row, and a body row.
    return len(block_lines) >= 3 and any(_PIPE_SEPARATOR_RE.match(line) for line in block_lines)


# =====================================================================================
# Parse artifact saving
# =====================================================================================

_WINDOWS_FORBIDDEN_FILENAME_CHARS = frozenset('<>:"/\\|?*')
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"{prefix}{number}" for prefix in ("COM", "LPT") for number in "123456789¹²³"}
)
_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


def _safe_artifact_stem(name: str) -> str:
    stem = "".join(
        ch
        for ch in name.strip()
        if ch not in _WINDOWS_FORBIDDEN_FILENAME_CHARS and ord(ch) >= 32
    ).strip(" .")
    # Bound UTF-8 bytes too, leaving room for the temporary-file suffix on Linux.
    stem = stem[:80].encode("utf-8")[:160].decode("utf-8", errors="ignore")
    stem = stem.rstrip(" .") or "document"
    if stem.split(".", maxsplit=1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        stem = f"document_{stem}"
    return stem


def _raw_upload_stem(input_filename: str) -> str:
    filename = input_filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    return PurePosixPath(filename).stem


def _artifact_dir(input_filename: str, *, request_id: str) -> tuple[Path, str]:
    """Create one request's directory and retain a safe source name for its files."""
    if (
        not _REQUEST_ID_RE.fullmatch(request_id)
        or request_id.upper() in _WINDOWS_RESERVED_NAMES
    ):
        raise ValueError("request_id must be a safe, non-reserved directory name")
    raw_stem = _raw_upload_stem(input_filename)
    display_stem = _safe_artifact_stem(raw_stem)
    artifact_dir = Path(settings.parse_output_dir) / request_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir, display_stem


def _atomic_write_text(path: Path, content: str) -> None:
    """Replace a complete UTF-8 artifact without exposing a partially written file."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def save_parse_artifacts(
    response: ParseResponse,
    input_filename: str,
) -> list[str]:
    """Write Markdown in the request's directory. Returns saved paths."""
    if not response.markdown:
        # Surface a signal so an empty saved_files is not mistaken for a successful export.
        logger.warning(
            "markdown output requested but no markdown was produced for request_id=%s; no .md written",
            response.request_id,
        )
        return []

    artifact_dir, display_stem = _artifact_dir(input_filename, request_id=response.request_id)
    md_path = artifact_dir / f"{display_stem}.md"
    _atomic_write_text(md_path, response.markdown)
    return [str(md_path.resolve())]


def save_extraction_artifacts(
    data: dict[str, object],
    input_filename: str,
    *,
    request_id: str,
) -> list[str]:
    """Write JSON alongside the same request's Markdown. Returns saved paths."""
    artifact_dir, display_stem = _artifact_dir(input_filename, request_id=request_id)
    json_path = artifact_dir / f"{display_stem}.json"
    _atomic_write_text(json_path, json.dumps(data, indent=2, ensure_ascii=False))
    return [str(json_path.resolve())]
