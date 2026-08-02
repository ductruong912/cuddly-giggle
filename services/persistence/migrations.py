"""Apply the numbered SQL migrations, once, in order.

No Alembic: that would pull SQLAlchemy in for a handful of tables the code
otherwise talks to in plain SQL. Numbered files plus a ledger table is the whole
mechanism, and it is small enough to read in one sitting.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

from services.persistence.pool import DatabasePool


logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
MIGRATION_GLOB = "*.sql"
# Any constant works as long as every instance uses the same one; this is
# "cuddly" in hex, chosen only to be unlikely to collide with another app.
MIGRATION_LOCK_KEY = 0x000C0DD1

LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT        PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


@dataclass(frozen=True)
class Migration:
    """One numbered SQL file."""

    version: str
    sql: str


class MigrationRunner:
    """Bring the schema up to date, safely under concurrent startups."""

    def __init__(self, pool: DatabasePool, migrations_dir: Path = MIGRATIONS_DIR) -> None:
        self.pool = pool
        self.migrations_dir = migrations_dir

    def load(self) -> list[Migration]:
        """Read the migration files in version order."""
        if not self.migrations_dir.is_dir():
            raise FileNotFoundError(f"no migrations directory at {self.migrations_dir}")
        return [
            Migration(version=path.stem, sql=path.read_text(encoding="utf-8"))
            for path in sorted(self.migrations_dir.glob(MIGRATION_GLOB))
        ]

    def run(self) -> list[str]:
        """Apply every migration not yet recorded. Returns the versions applied.

        Two app instances starting together would otherwise race to create the
        same tables, so the whole run happens under a Postgres advisory lock.
        """
        migrations = self.load()
        applied: list[str] = []

        with self.pool.connection() as connection:
            connection.execute(LEDGER_DDL)
            connection.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
            try:
                done = self._applied_versions(connection)
                for migration in migrations:
                    if migration.version in done:
                        continue
                    logger.info("applying migration %s", migration.version)
                    connection.execute(migration.sql)
                    connection.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)",
                        (migration.version,),
                    )
                    applied.append(migration.version)
            finally:
                connection.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_KEY,))

        if applied:
            logger.info("applied %s migration(s): %s", len(applied), ", ".join(applied))
        else:
            logger.info("schema is up to date (%s migration(s) known)", len(migrations))
        return applied

    @staticmethod
    def _applied_versions(connection: Any) -> set[str]:
        rows = connection.execute("SELECT version FROM schema_migrations").fetchall()
        # dict_row is configured on the pool, but a caller may pass a plain
        # connection; handle both shapes rather than assuming one.
        return {row["version"] if isinstance(row, dict) else row[0] for row in rows}
