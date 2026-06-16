"""Output helpers: markdown table filtering and parse artifact saving."""
from __future__ import annotations

import logging
from pathlib import Path
import re

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


def _candidate_path(output_dir: Path, stem: str, suffix_number: int) -> Path:
    if suffix_number == 1:
        return output_dir / f"{stem}.md"
    return output_dir / f"{stem} ({suffix_number}).md"


def _write_unique_markdown(output_dir: Path, stem: str, markdown: str) -> Path:
    suffix_number = 1
    while True:
        path = _candidate_path(output_dir, stem, suffix_number)
        try:
            with path.open("x", encoding="utf-8") as file:
                file.write(markdown)
            return path
        except FileExistsError:
            suffix_number += 1


def save_parse_artifacts(
    response: ParseResponse,
    input_filename: str,
) -> list[str]:
    output_dir = Path(settings.parse_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = _safe_artifact_stem(Path(input_filename).stem)

    if response.markdown:
        md_path = _write_unique_markdown(output_dir, stem, response.markdown)
        return [str(md_path.resolve())]

    # Surface a signal so an empty saved_files is not mistaken for a successful export.
    logger.warning(
        "markdown output requested but no markdown was produced for request_id=%s; no .md written",
        response.request_id,
    )
    return []
