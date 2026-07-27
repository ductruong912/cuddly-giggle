"""Shared rate limiter instance for the API layer."""
from __future__ import annotations

# pyrefly: ignore [missing-import]
from slowapi import Limiter
# pyrefly: ignore [missing-import]
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
