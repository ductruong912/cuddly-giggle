"""Shared rate limiter instance for the API layer."""
from __future__ import annotations

# pyrefly: ignore [missing-import]
from slowapi import Limiter
# pyrefly: ignore [missing-import]
from slowapi.util import get_remote_address

from config.config import settings


# The default limit is what SlowAPIMiddleware applies to every route; the heavier
# extraction routes narrow it further with their own @limiter.limit decorator.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.rate_limit_default],
)
