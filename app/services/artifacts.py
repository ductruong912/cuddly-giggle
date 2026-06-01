from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import settings
from app.domain.schemas import ParseResponse


logger = logging.getLogger(__name__)


def save_parse_artifacts(
    response: ParseResponse,
    input_filename: str,
    output_basename: str | None = None,
) -> list[str]:
    output_dir = Path(settings.parse_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = output_basename.strip() if output_basename else Path(input_filename).stem
    stem = "".join(ch for ch in stem if ch.isalnum() or ch in {"-", "_", "."}).strip(".")
    if not stem:
        stem = "document"
    stem = f"{stem}_{response.request_id}"

    if response.markdown:
        md_path = output_dir / f"{stem}.md"
        md_path.write_text(response.markdown, encoding="utf-8")
        return [str(md_path.resolve())]

    # Surface a signal so an empty saved_files is not mistaken for a successful export.
    logger.warning(
        "markdown output requested but no markdown was produced for request_id=%s; no .md written",
        response.request_id,
    )
    return []
