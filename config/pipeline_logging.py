"""Context helpers for pipeline logs and diagnostics."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar


_source_document: ContextVar[str | None] = ContextVar("source_document", default=None)


@contextmanager
def source_document_context(filename: str) -> Iterator[None]:
    """Carry the uploaded document's own name down into the engines.

    Uploads are staged under a UUID, so by the time a page reaches OCR its path
    says nothing about which document it came from. Diagnostics that end up on
    disk need the real name to be worth anything.
    """
    token = _source_document.set(filename)
    try:
        yield
    finally:
        _source_document.reset(token)


def current_source_document() -> str | None:
    return _source_document.get()


def pipeline_message(
    label_or_message: str,
    message: str | None = None,
) -> str:
    """Return terminal text without internal phase labels."""
    if message is None:
        return label_or_message
    if label_or_message.startswith("PHASE "):
        return message
    return f"{label_or_message} {message}"
