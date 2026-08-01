"""Read and write extraction history.

Plain SQL rather than an ORM: there are two tables, the queries are short, and
an ORM would be the largest dependency in the project for no gain.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import json
import logging
from typing import Any

from services.persistence.pool import DatabasePool


logger = logging.getLogger(__name__)

PO_DATE_FORMAT = "%d-%m-%Y"
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500

_INSERT_EXTRACTION = """
INSERT INTO extractions (
    request_id, source_filename, route, engine, page_count,
    po_number, po_date, validation_status, attempts, healed,
    data, issues, markdown, duration_ms
) VALUES (
    %(request_id)s, %(source_filename)s, %(route)s, %(engine)s, %(page_count)s,
    %(po_number)s, %(po_date)s, %(validation_status)s, %(attempts)s, %(healed)s,
    %(data)s, %(issues)s, %(markdown)s, %(duration_ms)s
)
ON CONFLICT (request_id) DO UPDATE SET
    data = EXCLUDED.data,
    issues = EXCLUDED.issues,
    validation_status = EXCLUDED.validation_status,
    attempts = EXCLUDED.attempts,
    healed = EXCLUDED.healed
RETURNING id
"""

_INSERT_ITEM = """
INSERT INTO extraction_items (
    extraction_id, line_number, toto_number, customer_number,
    quantity, unit_price, extension
) VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (extraction_id, line_number) DO UPDATE SET
    toto_number = EXCLUDED.toto_number,
    customer_number = EXCLUDED.customer_number,
    quantity = EXCLUDED.quantity,
    unit_price = EXCLUDED.unit_price,
    extension = EXCLUDED.extension
"""

_SELECT_COLUMNS = """
    id, request_id, source_filename, route, engine, page_count,
    po_number, po_date, validation_status, attempts, healed,
    data, issues, duration_ms, created_at
"""


@dataclass(frozen=True)
class ExtractionRecord:
    """One processed document, as it should be stored."""

    request_id: str
    source_filename: str
    route: str
    validation_status: str
    data: dict[str, Any]
    engine: str | None = None
    page_count: int = 0
    attempts: int = 1
    healed: bool = False
    issues: list[dict[str, Any]] = field(default_factory=list)
    markdown: str | None = None
    duration_ms: int | None = None


@dataclass(frozen=True)
class ExtractionQuery:
    """Filters for listing history."""

    po_number: str | None = None
    validation_status: str | None = None
    toto_number: str | None = None
    limit: int = DEFAULT_PAGE_SIZE
    offset: int = 0

    def normalised(self) -> ExtractionQuery:
        """Clamp paging so a caller cannot ask for the whole table at once."""
        return ExtractionQuery(
            po_number=self.po_number or None,
            validation_status=self.validation_status or None,
            toto_number=self.toto_number or None,
            limit=max(1, min(self.limit, MAX_PAGE_SIZE)),
            offset=max(0, self.offset),
        )


class ExtractionStore:
    """Persist extraction results and read them back."""

    def __init__(self, pool: DatabasePool) -> None:
        self.pool = pool

    def save(self, record: ExtractionRecord) -> int:
        """Write one extraction and its line items in a single transaction.

        Returns the row id. Re-processing the same request_id updates in place
        rather than duplicating, so a retry is idempotent.
        """
        payload = self._insert_parameters(record)
        items = self._line_items(record.data)

        with self.pool.connection() as connection:
            row = connection.execute(_INSERT_EXTRACTION, payload).fetchone()
            extraction_id = row["id"] if isinstance(row, dict) else row[0]
            if items:
                connection.execute(
                    "DELETE FROM extraction_items WHERE extraction_id = %s", (extraction_id,)
                )
                with connection.cursor() as cursor:
                    cursor.executemany(
                        _INSERT_ITEM,
                        [(extraction_id, *item) for item in items],
                    )

        logger.info(
            "persisted extraction id=%s request_id=%s items=%s",
            extraction_id,
            record.request_id,
            len(items),
        )
        return extraction_id

    def get(self, request_id: str) -> dict[str, Any] | None:
        """Fetch one extraction by request id, with its line items."""
        with self.pool.connection() as connection:
            row = connection.execute(
                f"SELECT {_SELECT_COLUMNS} FROM extractions WHERE request_id = %s",
                (request_id,),
            ).fetchone()
            if row is None:
                return None
            record = self._as_dict(row)
            record["items"] = self._items_for(connection, record["id"])
            return record

    def list(self, query: ExtractionQuery) -> list[dict[str, Any]]:
        """List extractions newest first, filtered by the query."""
        criteria = query.normalised()
        clause, parameters = self._where_clause(criteria)
        sql = (
            f"SELECT {_SELECT_COLUMNS} FROM extractions{clause} "
            "ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s"
        )
        parameters.extend([criteria.limit, criteria.offset])

        with self.pool.connection() as connection:
            rows = connection.execute(sql, tuple(parameters)).fetchall()
            return [self._as_dict(row) for row in rows]

    def count(self, query: ExtractionQuery) -> int:
        """Total rows matching the query's filters, ignoring paging."""
        clause, parameters = self._where_clause(query.normalised())
        with self.pool.connection() as connection:
            row = connection.execute(
                f"SELECT count(*) AS total FROM extractions{clause}", tuple(parameters)
            ).fetchone()
        return int(row["total"] if isinstance(row, dict) else row[0])

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _where_clause(criteria: ExtractionQuery) -> tuple[str, list[Any]]:
        """Build the WHERE clause and parameters shared by ``list`` and ``count``."""
        where: list[str] = []
        parameters: list[Any] = []

        if criteria.po_number:
            where.append("po_number = %s")
            parameters.append(criteria.po_number)
        if criteria.validation_status:
            where.append("validation_status = %s")
            parameters.append(criteria.validation_status)
        if criteria.toto_number:
            # EXISTS rather than a join: one row per extraction even when several
            # of its lines carry the same item code.
            where.append(
                "EXISTS (SELECT 1 FROM extraction_items i "
                "WHERE i.extraction_id = extractions.id AND i.toto_number = %s)"
            )
            parameters.append(criteria.toto_number)

        clause = f" WHERE {' AND '.join(where)}" if where else ""
        return clause, parameters

    @classmethod
    def _insert_parameters(cls, record: ExtractionRecord) -> dict[str, Any]:
        return {
            "request_id": record.request_id,
            "source_filename": record.source_filename,
            "route": record.route,
            "engine": record.engine,
            "page_count": record.page_count,
            "po_number": cls._text_or_none(record.data.get("po_number")),
            "po_date": cls._parse_po_date(record.data.get("po_date")),
            "validation_status": record.validation_status,
            "attempts": record.attempts,
            "healed": record.healed,
            # json.dumps rather than the raw dict: psycopg does not adapt a plain
            # dict to jsonb without a registered adapter.
            "data": json.dumps(record.data, ensure_ascii=False),
            "issues": json.dumps(record.issues, ensure_ascii=False),
            "markdown": record.markdown,
            "duration_ms": record.duration_ms,
        }

    @staticmethod
    def _text_or_none(value: Any) -> str | None:
        text = str(value).strip() if value is not None else ""
        return text or None

    @staticmethod
    def _parse_po_date(value: Any) -> date | None:
        """Best effort: an unparseable date is kept in `data` and stored as NULL.

        The date is denormalised only to support range queries. A record that
        failed validation may well carry a malformed one, and refusing to store
        the row for that reason would lose exactly the records worth reviewing.
        """
        if not value:
            return None
        try:
            return datetime.strptime(str(value).strip(), PO_DATE_FORMAT).date()
        except ValueError:
            logger.debug("po_date %r is not %s; storing NULL", value, PO_DATE_FORMAT)
            return None

    @classmethod
    def _line_items(cls, data: dict[str, Any]) -> list[tuple[Any, ...]]:
        items = data.get("items")
        if not isinstance(items, list):
            return []
        rows: list[tuple[Any, ...]] = []
        for line_number, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            toto_number = cls._text_or_none(item.get("toto_number"))
            if toto_number is None:
                continue
            rows.append(
                (
                    line_number,
                    toto_number,
                    cls._text_or_none(item.get("customer_number")),
                    cls._number_or_zero(item.get("quantity")),
                    cls._number_or_zero(item.get("unit_price")),
                    cls._number_or_none(item.get("extension")),
                )
            )
        return rows

    @staticmethod
    def _number_or_none(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _number_or_zero(cls, value: Any) -> float:
        parsed = cls._number_or_none(value)
        return 0.0 if parsed is None else parsed

    @staticmethod
    def _items_for(connection: Any, extraction_id: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT line_number, toto_number, customer_number, quantity, unit_price, extension "
            "FROM extraction_items WHERE extraction_id = %s ORDER BY line_number",
            (extraction_id,),
        ).fetchall()
        return [dict(row) if not isinstance(row, dict) else row for row in rows]

    @staticmethod
    def _as_dict(row: Any) -> dict[str, Any]:
        record = dict(row)
        for key in ("po_date", "created_at"):
            value = record.get(key)
            if hasattr(value, "isoformat"):
                record[key] = value.isoformat()
        return record
