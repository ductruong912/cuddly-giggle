"""Output helpers: markdown table filtering and parse artifact saving."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path, PurePosixPath
import re
import shutil
from typing import Any

from config.config import Settings, settings
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


def _artifact_dir(input_filename: str) -> tuple[Path, str]:
    """Return the output directory for a document plus the stem to name files with.

    The directory is created but never wiped: two concurrent uploads sharing a
    filename would otherwise delete each other's results mid-write. Both artifacts
    are overwritten in place instead, which is idempotent and safe to interleave.
    """
    raw_stem = _raw_upload_stem(input_filename)
    display_stem = _safe_artifact_stem(raw_stem)
    artifact_dir = Path(settings.parse_output_dir) / _artifact_folder_name(raw_stem, display_stem)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir, display_stem


def save_parse_artifacts(
    response: ParseResponse,
    input_filename: str,
) -> list[str]:
    """Write the parsed Markdown next to the source document's name. Returns saved paths."""
    if not response.markdown:
        # Surface a signal so an empty saved_files is not mistaken for a successful export.
        logger.warning(
            "markdown output requested but no markdown was produced for request_id=%s; no .md written",
            response.request_id,
        )
        return []

    artifact_dir, display_stem = _artifact_dir(input_filename)
    md_path = artifact_dir / f"{display_stem}.md"
    md_path.write_text(response.markdown, encoding="utf-8")
    return [str(md_path.resolve())]


def save_extraction_artifacts(
    data: dict[str, object],
    input_filename: str,
) -> list[str]:
    """Write the structured extraction result as JSON. Returns saved paths."""
    artifact_dir, display_stem = _artifact_dir(input_filename)
    json_path = artifact_dir / f"{display_stem}.json"
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return [str(json_path.resolve())]


# =====================================================================================
# Visual page artifact saving & retrieval
# =====================================================================================

_REQUEST_ID_SAFE_RE = re.compile(r"^req_[a-zA-Z0-9_-]{1,64}$")


def get_page_visual_dir(request_id: str, app_settings: Settings = settings) -> Path:
    """Return the directory for a request's visual artifacts, rejecting invalid IDs."""
    if not _REQUEST_ID_SAFE_RE.match(request_id):
        raise ValueError(f"Invalid request_id for visual artifact: {request_id}")
    root = Path(app_settings.parse_output_dir).resolve()
    target = (root / f"visual_{request_id}").resolve()
    if not str(target).startswith(str(root)):
        raise ValueError("Path traversal detected in visual artifact directory")
    target.mkdir(parents=True, exist_ok=True)
    return target


def save_page_visual_image(
    request_id: str,
    page_index: int,
    image: Any,
    app_settings: Settings = settings,
) -> Path:
    """Save a page image as PNG for visualization."""
    target_dir = get_page_visual_dir(request_id, app_settings)
    out_file = target_dir / f"page_{page_index}.png"

    if isinstance(image, bytes):
        out_file.write_bytes(image)
    elif isinstance(image, (str, Path)) and Path(image).is_file():
        shutil.copyfile(str(image), str(out_file))
    elif hasattr(image, "shape"):
        try:
            import cv2

            cv2.imwrite(str(out_file), image)
        except Exception:
            from PIL import Image

            if len(image.shape) == 3 and image.shape[2] == 3:
                im = Image.fromarray(image[:, :, ::-1])
            else:
                im = Image.fromarray(image)
            im.save(str(out_file), format="PNG")
    else:
        raise TypeError(f"Unsupported image type for visual artifact: {type(image)}")

    return out_file


def get_page_visual_image_path(
    request_id: str,
    page_index: int,
    app_settings: Settings = settings,
) -> Path | None:
    """Look up the path of a saved page image, safely checking against path traversal."""
    if not _REQUEST_ID_SAFE_RE.match(request_id) or page_index < 0:
        return None
    root = Path(app_settings.parse_output_dir).resolve()
    target = (root / f"visual_{request_id}" / f"page_{page_index}.png").resolve()
    if not str(target).startswith(str(root)):
        return None
    if not target.is_file():
        return None
    return target
