from __future__ import annotations

from functools import lru_cache

from app.services.parsing.orchestrator import ParseOrchestrator


@lru_cache(maxsize=1)
def get_orchestrator() -> ParseOrchestrator:
    return ParseOrchestrator()
