"""The connection pool, and the one place its lifecycle is owned.

Opened during application startup and closed on shutdown, so no request ever
pays connection setup and a restart never leaks server-side sessions.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import logging
from typing import Any

from config.config import Settings, settings


logger = logging.getLogger(__name__)


class DatabaseUnavailable(RuntimeError):
    """The database is configured but cannot be reached or used right now."""


class DatabasePool:
    """Own a psycopg connection pool for the process.

    The driver is imported lazily so a deployment with no ``DATABASE_URL`` — and
    therefore no psycopg installed — still starts.
    """

    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings
        self._pool: Any | None = None

    @property
    def is_open(self) -> bool:
        return self._pool is not None

    def open(self) -> None:
        """Create and open the pool. Raises if the database cannot be reached."""
        if self._pool is not None:
            return

        connection_pool_class, dict_row = self._import_driver()
        statement_timeout = self.settings.database_statement_timeout_ms
        connect_kwargs: dict[str, Any] = {
            "connect_timeout": self.settings.database_connect_timeout_seconds,
            "row_factory": dict_row,
        }
        if statement_timeout > 0:
            # Server-side cap: a query that hangs would otherwise hold an io slot
            # for as long as the network allows.
            connect_kwargs["options"] = f"-c statement_timeout={statement_timeout}"

        # open=False then open(): the psycopg docs flag that the constructor's
        # default may change, and an explicit open reports failure here rather
        # than on the first query.
        pool = connection_pool_class(
            self.settings.database_url,
            open=False,
            min_size=self.settings.database_pool_min_size,
            max_size=self.settings.database_pool_max_size,
            kwargs=connect_kwargs,
            name="cuddly-giggle",
        )
        try:
            pool.open(wait=True, timeout=float(self.settings.database_connect_timeout_seconds))
        except Exception as exc:
            logger.exception(
                "could not open the database pool for %s", self.settings.masked_database_url
            )
            pool.close()
            raise DatabaseUnavailable(f"database is unreachable: {exc}") from exc

        self._pool = pool
        logger.info(
            "database pool open: %s (min=%s max=%s)",
            self.settings.masked_database_url,
            self.settings.database_pool_min_size,
            self.settings.database_pool_max_size,
        )

    def close(self) -> None:
        """Close the pool. Safe to call when it was never opened."""
        if self._pool is None:
            return
        try:
            self._pool.close()
        except Exception:
            logger.exception("error while closing the database pool")
        finally:
            self._pool = None
            logger.info("database pool closed")

    @contextmanager
    def connection(self) -> Iterator[Any]:
        """Borrow a connection; the transaction commits on exit, rolls back on error."""
        if self._pool is None:
            raise DatabaseUnavailable("the database pool is not open")
        try:
            with self._pool.connection() as connection:
                yield connection
        except DatabaseUnavailable:
            raise
        except Exception as exc:
            logger.exception("database operation failed")
            raise DatabaseUnavailable(f"database operation failed: {exc}") from exc

    def check(self) -> bool:
        """Whether the pool can currently serve a working connection.

        Used by readiness. Runs ``SELECT 1`` rather than trusting pool state, so
        a database that went away while idle is actually detected.
        """
        if self._pool is None:
            return False
        try:
            with self._pool.connection() as connection:
                connection.execute("SELECT 1")
            return True
        except Exception:
            logger.warning("database readiness check failed", exc_info=True)
            return False

    @staticmethod
    def _import_driver() -> tuple[Any, Any]:
        try:
            # pyrefly: ignore [missing-import]
            from psycopg.rows import dict_row

            # pyrefly: ignore [missing-import]
            from psycopg_pool import ConnectionPool
        except ImportError as exc:
            raise DatabaseUnavailable(
                "DATABASE_URL is set but psycopg is not installed; "
                "install psycopg[binary] and psycopg-pool"
            ) from exc
        return ConnectionPool, dict_row
