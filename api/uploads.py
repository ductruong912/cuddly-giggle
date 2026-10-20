"""Read request bodies and stage uploaded files to disk without blocking the loop."""
from __future__ import annotations

from dataclasses import dataclass
from functools import partial
import json
import logging
from pathlib import Path
import tempfile
from typing import IO, Any
import uuid

# pyrefly: ignore [missing-import]
from fastapi import Request, UploadFile
from fastapi.responses import JSONResponse

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
_MULTIPART_REQUEST_OVERHEAD_BYTES = 1024 * 1024
_REQUEST_BODY_LIMIT_PATHS = frozenset(
    {"/v1/extract/local", "/v1/doc/ocr", "/v1/doc/ocr/result"}
)
_PROTECTED_PROJECT_DIRS = (
    ".git", ".paddlex", ".venv", "llama", "models", "outputs", "venv"
)
_PROTECTED_PATH_SETTINGS = (
    "llama_cpp_dir",
    "llama_cpp_models_dir",
    "paddlex_cache_home",
    "parse_output_dir",
    "preprocess_debug_dir",
)


def normalize_media_type(value: str) -> str:
    """Return the lowercase media type without parameters such as charset or boundary."""
    return value.partition(";")[0].strip().lower()


class _RequestBodyTooLarge(Exception):
    """Raised when a streamed request exceeds the endpoint's byte budget."""


class RequestBodyLimitMiddleware:
    """Bound upload and Markdown request bodies before FastAPI parses them."""

    def __init__(self, app: Any, *, max_upload_bytes: int) -> None:
        self.app = app
        self.max_upload_bytes = max_upload_bytes

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if (
            scope.get("type") != "http"
            or scope.get("method") != "POST"
            or scope.get("path") not in _REQUEST_BODY_LIMIT_PATHS
        ):
            await self.app(scope, receive, send)
            return

        headers = scope.get("headers", ())
        content_type = next(
            (
                value.decode("latin-1")
                for name, value in headers
                if name.lower() == b"content-type"
            ),
            "",
        )
        limit = self.max_upload_bytes
        if normalize_media_type(content_type) == MULTIPART_CONTENT_TYPE:
            # The actual file remains capped at max_upload_bytes by UploadStager;
            # this small allowance is for multipart boundaries and field headers.
            limit += _MULTIPART_REQUEST_OVERHEAD_BYTES

        content_lengths = [
            value for name, value in headers if name.lower() == b"content-length"
        ]
        if len(content_lengths) == 1:
            try:
                declared_size = int(content_lengths[0])
            except ValueError:
                declared_size = None
            if declared_size is not None and declared_size > limit:
                await self._send_too_large(scope, receive, send)
                return

        received_bytes = 0
        response_started = False

        async def limited_receive() -> dict[str, Any]:
            nonlocal received_bytes
            message = await receive()
            if message.get("type") == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > limit:
                    raise _RequestBodyTooLarge
            return message

        async def tracked_send(message: dict[str, Any]) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise
            await self._send_too_large(scope, receive, send)

    async def _send_too_large(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        response = JSONResponse(
            status_code=413,
            content={"detail": "Request body exceeds the configured size limit."},
        )
        await response(scope, receive, send)


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _has_symlink_component(path: Path) -> bool:
    absolute_path = path if path.is_absolute() else Path.cwd() / path
    current = Path(absolute_path.anchor)
    for part in absolute_path.parts[1:]:
        if part == "..":
            current = current.parent
            continue
        if part == ".":
            continue
        current = current / part
        if current.is_symlink():
            return True
    return False


def _safe_temp_root(app_settings: Settings) -> Path:
    configured_path = Path(app_settings.temp_dir).expanduser()
    if _has_symlink_component(configured_path):
        raise ValueError("DOC_TEMP_DIR must not contain symbolic links.")

    temp_root = configured_path.resolve()
    filesystem_root = Path(temp_root.anchor)
    if temp_root == filesystem_root:
        raise ValueError(
            "DOC_TEMP_DIR must be a dedicated directory, not a filesystem root."
        )

    repo_root = Path(__file__).resolve().parents[1]
    if temp_root == repo_root or temp_root in repo_root.parents:
        raise ValueError(
            "DOC_TEMP_DIR must not be the repository root or one of its parents."
        )

    shared_temp_root = Path(tempfile.gettempdir()).resolve()
    if temp_root == shared_temp_root or temp_root in shared_temp_root.parents:
        raise ValueError(
            "DOC_TEMP_DIR must not be a shared temporary directory or its parent."
        )

    protected_paths = [repo_root / name for name in _PROTECTED_PROJECT_DIRS]
    for setting_name in _PROTECTED_PATH_SETTINGS:
        configured_value = getattr(app_settings, setting_name, None)
        if configured_value:
            protected_paths.append(Path(configured_value).expanduser().resolve())
    if any(_paths_overlap(temp_root, path.resolve()) for path in protected_paths):
        raise ValueError(
            "DOC_TEMP_DIR must not overlap application data, model, or cache directories."
        )
    if temp_root.exists() and not temp_root.is_dir():
        raise ValueError("DOC_TEMP_DIR must be a directory.")
    return temp_root


def _is_owned_staged_file(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    stem, separator, suffix = path.name.partition(".")
    if len(stem) != 32 or any(character not in "0123456789abcdef" for character in stem):
        return False
    return not separator or (
        1 <= len(suffix) <= 12 and suffix.isascii() and suffix.isalnum()
    )


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
    if (
        normalize_media_type(request.headers.get("content-type", ""))
        != MULTIPART_CONTENT_TYPE
    ):
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
    if normalize_media_type(request.headers.get("content-type", "")) == "application/json":
        raw_body = await request.body()
        try:
            payload = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidRequestPayload("Invalid JSON body.") from exc
        if not isinstance(payload, dict) or "markdown" not in payload:
            raise InvalidRequestPayload(
                "JSON payload must be an object containing a 'markdown' key."
            )
        markdown = payload["markdown"]
        if not isinstance(markdown, str):
            raise InvalidRequestPayload("JSON 'markdown' value must be a string.")
        return markdown

    raw_body = await request.body()
    try:
        return raw_body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidRequestPayload("Request body must be UTF-8 encoded.") from exc


async def read_markdown_upload(upload: UploadFile) -> str:
    """Decode an uploaded .md/.markdown file."""
    try:
        raw_body = await upload.read(settings.max_upload_bytes + 1)
        if len(raw_body) > settings.max_upload_bytes:
            limit_mb = settings.max_upload_bytes / (1024 * 1024)
            raise UploadTooLarge(f"Upload exceeds the {limit_mb:.0f} MB limit.")
        return raw_body.decode("utf-8")
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

        temp_root = _safe_temp_root(self.settings)
        temp_path = temp_root / f"{uuid.uuid4().hex}{suffix}"
        size_bytes = await self._limiter.run_with_cleanup(
            self._write_to_disk,
            upload.file,
            temp_path,
            cleanup=partial(self._discard_path, temp_path),
            cleanup_on_success=False,
        )
        return StagedUpload(
            path=temp_path,
            filename=upload.filename or temp_path.name,
            size_bytes=size_bytes,
        )

    def discard(self, staged: StagedUpload | None) -> None:
        """Delete a staged file; safe to call when staging never completed."""
        if staged is None:
            return
        self._discard_path(staged.path)

    @staticmethod
    def _discard_path(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.exception("could not remove staged upload %s", path)

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
    temp_root = _safe_temp_root(app_settings)
    if not temp_root.is_dir():
        return 0
    removed = 0
    for leftover in temp_root.iterdir():
        if not _is_owned_staged_file(leftover):
            continue
        try:
            leftover.unlink()
            removed += 1
        except OSError:
            logger.exception("could not remove leftover staged file %s", leftover)
    if removed:
        logger.info("removed %s staged file(s) left by a previous run", removed)
    return removed
