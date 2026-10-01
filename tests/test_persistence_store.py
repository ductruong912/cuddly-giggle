"""Database pool failures, credential masking and record mapping without PostgreSQL."""
from __future__ import annotations

import dataclasses
from datetime import date
import json
from typing import Any

import pytest

from config.config import Settings, mask_database_url, settings
from services.persistence import (
    DatabasePool,
    DatabaseUnavailable,
    ExtractionQuery,
    ExtractionRecord,
    ExtractionStore,
)
from services.persistence.extraction_store import MAX_PAGE_SIZE


def configured(url: str, **overrides: object) -> Settings:
    return dataclasses.replace(settings, database_url=url, **overrides)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql://docpipe:secret@db:5432/app", "postgresql://docpipe:***@db:5432/app"),
        ("postgresql://docpipe@db:5432/app", "postgresql://docpipe@db:5432/app"),
        ("postgresql://db:5432/app", "postgresql://db:5432/app"),
        ("", ""),
    ],
)
def test_the_password_never_reaches_a_log_line(url: str, expected: str) -> None:
    """Connection strings routinely land in startup lines and error messages."""
    assert mask_database_url(url) == expected


def test_a_password_with_an_at_sign_is_still_masked() -> None:
    masked = mask_database_url("postgresql://user:p@ss@db:5432/app")

    assert "p@ss" not in masked
    assert masked.endswith("@db:5432/app")


def test_settings_expose_the_masked_url() -> None:
    app_settings = configured("postgresql://u:hunter2@db:5432/app")

    assert "hunter2" not in app_settings.masked_database_url


def test_persistence_is_off_without_a_url() -> None:
    assert configured("").persistence_enabled is False
    assert configured("postgresql://db/app").persistence_enabled is True


def test_an_unopened_pool_refuses_to_hand_out_connections() -> None:
    pool = DatabasePool(configured("postgresql://u:p@127.0.0.1:5432/db"))

    assert pool.is_open is False
    assert pool.check() is False
    pool.close()
    with pytest.raises(DatabaseUnavailable, match="not open"):
        with pool.connection():
            pass


def test_an_unreachable_database_fails_at_startup() -> None:
    """Better to fail on boot than on the first upload."""
    pytest.importorskip("psycopg_pool", reason="the driver is needed to attempt a connection")
    # Port 1 is reserved and never listening.
    pool = DatabasePool(
        configured("postgresql://u:p@127.0.0.1:1/db", database_connect_timeout_seconds=1)
    )

    with pytest.raises(DatabaseUnavailable, match="unreachable"):
        pool.open()

    assert pool.is_open is False


def test_a_missing_driver_is_reported_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    """DATABASE_URL set but psycopg absent must say so, not raise ImportError."""
    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.startswith(("psycopg", "psycopg_pool")):
            raise ImportError(f"no module named {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    pool = DatabasePool(configured("postgresql://u:p@db:5432/app"))

    with pytest.raises(DatabaseUnavailable, match="psycopg is not installed"):
        pool.open()


class FakeCursor:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows
        self.executemany_calls: list[tuple[str, list[Any]]] = []

    def executemany(self, sql: str, params_seq: list[Any]) -> None:
        self.executemany_calls.append((sql, list(params_seq)))

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[Any]:
        return self._rows

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class FakeConnection:
    """Records every statement and returns queued results."""

    def __init__(self, results: list[Any] | None = None) -> None:
        self.statements: list[tuple[str, Any]] = []
        self.results = list(results or [])
        self.cursors: list[FakeCursor] = []

    def execute(self, sql: str, params: Any = None) -> FakeCursor:
        self.statements.append((" ".join(sql.split()), params))
        rows = self.results.pop(0) if self.results else []
        return FakeCursor(rows)

    def cursor(self) -> FakeCursor:
        cursor = FakeCursor([])
        self.cursors.append(cursor)
        return cursor


class FakePool:
    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection

    def connection(self):  # noqa: ANN201 - context manager duck-typed for the store
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            yield self._connection

        return _ctx()


ORDER = {
    "po_number": "215497",
    "po_date": "05-06-2026",
    "items": [
        {
            "toto_number": "TX703AR",
            "customer_number": "CT-9001",
            "quantity": 4,
            "unit_price": 1250000,
            "extension": 5000000,
        },
        {
            "toto_number": "CW823RJ",
            "customer_number": None,
            "quantity": 2,
            "unit_price": 3450000,
            "extension": None,
        },
    ],
}


def record(**overrides: Any) -> ExtractionRecord:
    defaults: dict[str, Any] = {
        "request_id": "req_abc123",
        "source_filename": "po.pdf",
        "route": "local",
        "validation_status": "valid",
        "data": ORDER,
        "engine": "paddleocr_vl",
        "page_count": 2,
        "attempts": 1,
        "healed": False,
        "issues": [],
        "markdown": "# doc",
        "duration_ms": 4200,
    }
    defaults.update(overrides)
    return ExtractionRecord(**defaults)


def store_with(connection: FakeConnection) -> ExtractionStore:
    return ExtractionStore(FakePool(connection))


def test_the_header_is_denormalised_for_lookup() -> None:
    connection = FakeConnection(results=[[{"id": 77}]])

    assert store_with(connection).save(record()) == 77

    sql, params = connection.statements[0]
    assert "ON CONFLICT (request_id) DO UPDATE" in sql
    assert isinstance(params["data"], str)
    assert json.loads(params["data"])["po_number"] == "215497"
    assert json.loads(params["issues"]) == []
    assert params["po_number"] == "215497"
    assert params["po_date"] == date(2026, 6, 5), "DD-MM-YYYY parsed into a real DATE"


def test_an_unparseable_date_is_stored_as_null() -> None:
    """Records that failed validation are exactly the ones worth keeping."""
    connection = FakeConnection(results=[[{"id": 1}]])

    store_with(connection).save(record(data={**ORDER, "po_date": "2026/06/05"}))

    _, params = connection.statements[0]
    assert params["po_date"] is None
    assert json.loads(params["data"])["po_date"] == "2026/06/05", "the raw value survives"


def test_line_items_are_written_relationally() -> None:
    connection = FakeConnection(results=[[{"id": 42}]])

    store_with(connection).save(record())

    assert any(sql.startswith("DELETE") for sql, _ in connection.statements)
    assert connection.cursors, "line items go through executemany"
    _, rows = connection.cursors[0].executemany_calls[0]
    assert [row[0] for row in rows] == [42, 42], "each row carries the extraction id"
    assert [row[1] for row in rows] == [1, 2], "line numbers are 1-based"
    assert [row[2] for row in rows] == ["TX703AR", "CW823RJ"]
    assert rows[1][6] is None, "a null extension stays null"


def test_a_record_with_no_items_writes_no_item_rows() -> None:
    connection = FakeConnection(results=[[{"id": 1}]])

    store_with(connection).save(record(data={"po_number": "1", "po_date": "05-06-2026"}))

    assert connection.cursors == []


def test_items_without_a_code_are_skipped() -> None:
    """A blank item code cannot be looked up and would only add noise."""
    connection = FakeConnection(results=[[{"id": 1}]])
    data = {**ORDER, "items": [{"toto_number": "  ", "quantity": 1, "unit_price": 1}]}

    store_with(connection).save(record(data=data))

    assert connection.cursors == []


def test_listing_filters_by_purchase_order() -> None:
    connection = FakeConnection(results=[[]])

    store_with(connection).list(ExtractionQuery(po_number="215497"))

    sql, params = connection.statements[0]
    assert "WHERE po_number = %s" in sql
    assert params[0] == "215497"
    assert "ORDER BY created_at DESC" in sql


def test_listing_filters_by_item_code_without_duplicating_rows() -> None:
    connection = FakeConnection(results=[[]])

    store_with(connection).list(ExtractionQuery(toto_number="TX703AR"))

    sql, params = connection.statements[0]
    assert "EXISTS" in sql, "a join would return one row per matching line"
    assert params[0] == "TX703AR"


@pytest.mark.parametrize(
    ("requested", "expected"),
    [(0, 1), (-5, 1), (10, 10), (MAX_PAGE_SIZE + 1000, MAX_PAGE_SIZE)],
)
def test_paging_is_clamped(requested: int, expected: int) -> None:
    """A caller must not be able to ask for the whole table in one request."""
    query = ExtractionQuery(limit=requested, offset=-10).normalised()
    assert query.limit == expected
    assert query.offset == 0


def test_getting_a_missing_record_returns_none() -> None:
    connection = FakeConnection(results=[[]])

    assert store_with(connection).get("req_missing") is None


def test_getting_a_record_includes_its_items() -> None:
    header = {"id": 5, "request_id": "req_x", "po_date": date(2026, 6, 5)}
    items = [{"line_number": 1, "toto_number": "TX703AR"}]
    connection = FakeConnection(results=[[header], items])

    found = store_with(connection).get("req_x")

    assert found is not None
    assert found["items"] == items
    assert found["po_date"] == "2026-06-05", "dates are serialised for JSON"
