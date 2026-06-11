from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import settings
from app.domain.schemas import ParseResponse


logger = logging.getLogger(__name__)


_WINDOWS_FORBIDDEN_FILENAME_CHARS = frozenset('<>:"/\\|?*')
_IGNORED_OUTPUT_BASENAME_VALUES = frozenset({"string"})


def _safe_artifact_stem(name: str) -> str:
    stem = "".join(
        ch
        for ch in name.strip()
        if ch not in _WINDOWS_FORBIDDEN_FILENAME_CHARS and ord(ch) >= 32
    ).strip(" .")
    return stem or "document"


def _normalize_output_basename(output_basename: str | None) -> str | None:
    if output_basename is None:
        return None
    normalized = output_basename.strip()
    if not normalized or normalized in _IGNORED_OUTPUT_BASENAME_VALUES:
        return None
    return normalized


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
    output_basename: str | None = None,
) -> list[str]:
    output_dir = Path(settings.parse_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_stem = _normalize_output_basename(output_basename) or Path(input_filename).stem
    stem = _safe_artifact_stem(raw_stem)

    if response.markdown:
        md_path = _write_unique_markdown(output_dir, stem, response.markdown)
        return [str(md_path.resolve())]

    # Surface a signal so an empty saved_files is not mistaken for a successful export.
    logger.warning(
        "markdown output requested but no markdown was produced for request_id=%s; no .md written",
        response.request_id,
    )
    return []
