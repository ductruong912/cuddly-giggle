"""Postgres persistence for extraction history.

Optional: with no ``DATABASE_URL`` the service behaves exactly as before and
writes results to files only.
"""
from __future__ import annotations

from services.persistence.extraction_store import (
    ExtractionQuery,
    ExtractionRecord,
    ExtractionStore,
)
from services.persistence.migrations import Migration, MigrationRunner
from services.persistence.pool import DatabasePool, DatabaseUnavailable


__all__ = [
    "DatabasePool",
    "DatabaseUnavailable",
    "ExtractionQuery",
    "ExtractionRecord",
    "ExtractionStore",
    "Migration",
    "MigrationRunner",
]
