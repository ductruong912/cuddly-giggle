"""Output helpers: markdown table filtering and parse artifact saving."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path, PurePosixPath
import re
import shutil

from app.core.config import settings
from app.domain.schemas import ParseResponse


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


def _safe_artifact_stem(name: str) -> str:
    stem = "".join(
        ch
        for ch in name.strip()
        if ch not in _WINDOWS_FORBIDDEN_FILENAME_CHARS and ord(ch) >= 32
    ).strip(" .")
    return stem or "document"


def _raw_upload_stem(input_filename: str) -> str:
    filename = input_filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    return PurePosixPath(filename).stem


def _artifact_folder_name(raw_stem: str, display_stem: str) -> str:
    if raw_stem == display_stem:
        return display_stem
    digest = hashlib.sha256(raw_stem.encode("utf-8")).hexdigest()
    return f"{display_stem}-{digest}"


def _replace_artifact_dir(output_dir: Path, stem: str) -> Path:
    artifact_dir = output_dir / stem
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir


def save_parse_artifacts(
    response: ParseResponse,
    input_filename: str,
) -> list[str]:
    if not response.markdown:
        # Surface a signal so an empty saved_files is not mistaken for a successful export.
        logger.warning(
            "markdown output requested but no markdown was produced for request_id=%s; no .md written",
            response.request_id,
        )
        return []

    raw_stem = _raw_upload_stem(input_filename)
    display_stem = _safe_artifact_stem(raw_stem)
    artifact_dir = _replace_artifact_dir(
        Path(settings.parse_output_dir),
        _artifact_folder_name(raw_stem, display_stem),
    )
    md_path = artifact_dir / f"{display_stem}.md"
    md_path.write_text(response.markdown, encoding="utf-8")
    return [str(md_path.resolve())]
