"""Read request bodies and stage uploaded files to disk without blocking the loop."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import shutil
from typing import IO, Any
import uuid

# pyrefly: ignore [missing-import]
from fastapi import Request, UploadFile

from api.errors import (
    InvalidRequestPayload,
    MissingUpload,
    UnsupportedContentType,
    UnsupportedUploadType,
    UploadTooLarge,
)
from config.config import Settings, settings
from services.concurrency import StageLimiter


logger = logging.getLogger(__name__)

MULTIPART_CONTENT_TYPE = "multipart/form-data"
MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})
_COPY_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class StagedUpload:
    """An uploaded document written to the temp directory for engine consumption."""

    path: Path
    filename: str
    size_bytes: int

    @property
    def suffix(self) -> str:
        return self.path.suffix.lower()


async def resolve_upload(request: Request, file: UploadFile | None) -> UploadFile:
    """Return the uploaded file, whether FastAPI bound it or it needs form parsing."""
    if MULTIPART_CONTENT_TYPE not in request.headers.get("content-type", ""):
        raise UnsupportedContentType(
            f"This route requires a {MULTIPART_CONTENT_TYPE} file upload."
        )
    uploaded = file
    if uploaded is None:
        form = await request.form()
        uploaded = form.get("file")  # type: ignore[assignment]
    if uploaded is None or not (hasattr(uploaded, "filename") and hasattr(uploaded, "file")):
        raise MissingUpload("Missing 'file' field in multipart/form-data upload.")
    return uploaded


def upload_suffix(upload: UploadFile) -> str:
    """Lowercase filename suffix of an upload, or an empty string when unnamed."""
    return Path(upload.filename or "").suffix.lower()


async def read_markdown_payload(request: Request) -> str:
    """Decode a raw Markdown body sent as text/markdown, text/plain, or JSON."""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        raw_body = await request.body()
        try:
            payload = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidRequestPayload("Invalid JSON body.") from exc
        if not isinstance(payload, dict) or "markdown" not in payload:
            raise InvalidRequestPayload(
                "JSON payload must be an object containing a 'markdown' key."
            )
        return str(payload["markdown"])

    raw_body = await request.body()
    try:
        return raw_body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidRequestPayload("Request body must be UTF-8 encoded.") from exc


async def read_markdown_upload(upload: UploadFile) -> str:
    """Decode an uploaded .md/.markdown file."""
    try:
        return (await upload.read()).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidRequestPayload("Markdown file must be UTF-8 encoded.") from exc


class UploadStager:
    """Write uploads to the temp directory under a size cap, off the event loop."""

    def __init__(self, limiter: StageLimiter, app_settings: Settings = settings) -> None:
        self.settings = app_settings
        self._limiter = limiter

    async def stage(
        self,
        upload: UploadFile,
        *,
        allowed_suffixes: frozenset[str] | set[str],
        unsupported_message: str,
    ) -> StagedUpload:
        """Validate the suffix and copy the upload to a unique temp path.

        Raises:
            UnsupportedUploadType: the suffix is not in ``allowed_suffixes``.
            UploadTooLarge: the upload exceeds ``MAX_UPLOAD_BYTES``.
        """
        suffix = upload_suffix(upload)
        if suffix not in allowed_suffixes:
            raise UnsupportedUploadType(unsupported_message)

        declared_size = getattr(upload, "size", None)
        if isinstance(declared_size, int) and declared_size > self.settings.max_upload_bytes:
            raise UploadTooLarge(self._too_large_message(declared_size))

        temp_root = Path(self.settings.temp_dir)
        temp_path = temp_root / f"{uuid.uuid4().hex}{suffix}"
        size_bytes = await self._limiter.run(self._write_to_disk, upload.file, temp_path)
        return StagedUpload(
            path=temp_path,
            filename=upload.filename or temp_path.name,
            size_bytes=size_bytes,
        )

    def discard(self, staged: StagedUpload | None) -> None:
        """Delete a staged file; safe to call when staging never completed."""
        if staged is None:
            return
        try:
            staged.path.unlink(missing_ok=True)
        except OSError:
            logger.exception("could not remove staged upload %s", staged.path)

    def _write_to_disk(self, source: IO[Any], destination: Path) -> int:
        """Stream ``source`` to ``destination``, aborting once the size cap is passed."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        limit = self.settings.max_upload_bytes
        written = 0
        try:
            with destination.open("wb") as target:
                while True:
                    chunk = source.read(_COPY_CHUNK_BYTES)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > limit:
                        raise UploadTooLarge(self._too_large_message(written))
                    target.write(chunk)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        return written

    def _too_large_message(self, observed_bytes: int) -> str:
        limit_mb = self.settings.max_upload_bytes / (1024 * 1024)
        return (
            f"Upload exceeds the {limit_mb:.0f} MB limit "
            f"(received at least {observed_bytes / (1024 * 1024):.1f} MB)."
        )


def cleanup_temp_dir(app_settings: Settings = settings) -> int:
    """Remove staged files left behind by a previous run. Returns the count removed."""
    temp_root = Path(app_settings.temp_dir)
    if not temp_root.is_dir():
        return 0
    removed = 0
    for leftover in temp_root.iterdir():
        try:
            if leftover.is_file():
                leftover.unlink()
                removed += 1
            elif leftover.is_dir():
                shutil.rmtree(leftover, ignore_errors=True)
        except OSError:
            logger.exception("could not remove leftover staged file %s", leftover)
    if removed:
        logger.info("removed %s staged file(s) left by a previous run", removed)
    return removed
