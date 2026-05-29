from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import settings
from app.domain.schemas import OutputFormat, ParseResponse


logger = logging.getLogger(__name__)


def save_parse_artifacts(
    response: ParseResponse,
    input_filename: str,
    output_format: OutputFormat,
    output_basename: str | None = None,
) -> list[str]:
    output_dir = Path(settings.parse_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = output_basename.strip() if output_basename else Path(input_filename).stem
    stem = "".join(ch for ch in stem if ch.isalnum() or ch in {"-", "_", "."}).strip(".")
    if not stem:
        stem = "document"
    stem = f"{stem}_{response.request_id}"

    saved: list[str] = []
    if output_format in {OutputFormat.json, OutputFormat.both}:
        json_path = output_dir / f"{stem}.json"
        json_path.write_text(
            response.model_dump_json(indent=2, exclude_none=True),
            encoding="utf-8",
        )
        saved.append(str(json_path.resolve()))

    wants_markdown = output_format in {OutputFormat.markdown, OutputFormat.both}
    if wants_markdown and response.markdown:
        md_path = output_dir / f"{stem}.md"
        md_path.write_text(response.markdown, encoding="utf-8")
        saved.append(str(md_path.resolve()))
    elif wants_markdown:
        # Markdown was requested but the engine produced none. Surface a signal so an
        # empty saved_files (markdown-only) is not mistaken for a successful export.
        logger.warning(
            "markdown output requested (output_format=%s) but no markdown was produced "
            "for request_id=%s; no .md written",
            output_format.value,
            response.request_id,
        )

    return saved
