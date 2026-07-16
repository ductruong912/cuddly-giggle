"""Request-scoped helpers for concise pipeline lifecycle logs."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar


_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


@contextmanager
def request_logging_context(request_id: str) -> Iterator[None]:
    token = _request_id.set(request_id)
    try:
        yield
    finally:
        _request_id.reset(token)


def current_request_id() -> str | None:
    return _request_id.get()


def pipeline_message(
    label_or_message: str,
    message: str | None = None,
    *,
    request_id: str | None = None,
) -> str:
    """Return terminal text without internal phase or request identifiers."""
    del request_id
    if message is None:
        return label_or_message
    if label_or_message.startswith("PHASE "):
        return message
    return f"{label_or_message} {message}"
