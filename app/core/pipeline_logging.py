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


def pipeline_message(prefix: str, message: str, *, request_id: str | None = None) -> str:
    request_id = request_id or current_request_id()
    if request_id:
        return f"{prefix} [{request_id}] {message}"
    return f"{prefix} {message}"
