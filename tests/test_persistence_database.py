"""End-to-end persistence against a real PostgreSQL.

Skipped unless ``TEST_DATABASE_URL`` is set, because the SQL, the migrations and
the NUMERIC/JSONB round-trips cannot be verified against a fake connection.

    docker compose up -d postgres
    TEST_DATABASE_URL=postgresql://docpipe:docpipepass@127.0.0.1:5433/docpipeline pytest

The suite creates its own schema through the real migration runner and removes
the rows it wrote.
"""
from __future__ import annotations

import dataclasses
import os
from typing import Iterator
import uuid

import pytest

from config.config import settings
from services.persistence import (
    DatabasePool,
    ExtractionQuery,
    ExtractionRecord,
    ExtractionStore,
    MigrationRunner,
)


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to run the database integration tests",
)


@pytest.fixture(scope="module")
def pool() -> Iterator[DatabasePool]:
    database_pool = DatabasePool(
        dataclasses.replace(settings, database_url=TEST_DATABASE_URL, database_pool_max_size=4)
    )
    database_pool.open()
    MigrationRunner(database_pool).run()
    try:
        yield database_pool
    finally:
        database_pool.close()


@pytest.fixture
def store(pool: DatabasePool) -> Iterator[ExtractionStore]:
    written: list[str] = []
    extraction_store = ExtractionStore(pool)
    extraction_store._written = written  # type: ignore[attr-defined]
    yield extraction_store
    if written:
        with pool.connection() as connection:
            connection.execute(
                "DELETE FROM extractions WHERE request_id = ANY(%s)", (written,)
            )


def order(po_number: str) -> dict:
    return {
        "po_number": po_number,
        "po_date": "05-06-2026",
        "items": [
            {
                "toto_number": "TX703AR",
                "customer_number": "CT-9001",
                "quantity": 4,
                "unit_price": 1250000.5,
                "extension": 5000002.0,
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


def save(store: ExtractionStore, **overrides) -> tuple[str, int]:
    request_id = overrides.pop("request_id", f"req_{uuid.uuid4().hex[:12]}")
    po_number = overrides.pop("po_number", uuid.uuid4().hex[:10])
    record = ExtractionRecord(
        request_id=request_id,
        source_filename="po.pdf",
        route="local",
        validation_status=overrides.pop("validation_status", "valid"),
        data=overrides.pop("data", order(po_number)),
        engine="paddleocr_vl",
        page_count=2,
        **overrides,
    )
    row_id = store.save(record)
    store._written.append(request_id)  # type: ignore[attr-defined]
    return request_id, row_id


def test_migrations_create_the_schema(pool: DatabasePool) -> None:
    with pool.connection() as connection:
        rows = connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()

    tables = {row["table_name"] for row in rows}
    assert {"extractions", "extraction_items", "schema_migrations"} <= tables


def test_migrations_are_idempotent(pool: DatabasePool) -> None:
    """Every restart runs them; a second pass must apply nothing."""
    assert MigrationRunner(pool).run() == []


def test_a_record_round_trips(store: ExtractionStore) -> None:
    request_id, row_id = save(store)

    found = store.get(request_id)

    assert found is not None
    assert found["id"] == row_id
    assert found["validation_status"] == "valid"
    assert found["po_date"] == "2026-06-05"
    assert len(found["items"]) == 2


def test_decimal_money_survives_the_round_trip(store: ExtractionStore) -> None:
    """NUMERIC, not double precision: binary floats cannot hold decimal currency."""
    request_id, _ = save(store)

    items = store.get(request_id)["items"]

    assert float(items[0]["unit_price"]) == 1250000.5
    assert float(items[0]["extension"]) == 5000002.0
    assert items[1]["extension"] is None


def test_jsonb_keeps_the_full_record(store: ExtractionStore) -> None:
    po_number = uuid.uuid4().hex[:10]
    request_id, _ = save(store, po_number=po_number)

    found = store.get(request_id)

    assert found["data"]["po_number"] == po_number
    assert found["data"]["items"][0]["toto_number"] == "TX703AR"


def test_resaving_the_same_request_updates_in_place(store: ExtractionStore) -> None:
    po_number = uuid.uuid4().hex[:10]
    request_id, first_id = save(store, po_number=po_number)

    _, second_id = save(
        store,
        request_id=request_id,
        po_number=po_number,
        validation_status="needs_review",
        data=order(po_number),
    )

    assert second_id == first_id, "a retry must not duplicate the row"
    assert store.get(request_id)["validation_status"] == "needs_review"


def test_line_items_are_replaced_not_appended(store: ExtractionStore) -> None:
    po_number = uuid.uuid4().hex[:10]
    request_id, _ = save(store, po_number=po_number)
    shorter = {**order(po_number), "items": [order(po_number)["items"][0]]}

    save(store, request_id=request_id, po_number=po_number, data=shorter)

    assert len(store.get(request_id)["items"]) == 1


def test_lookup_by_purchase_order_number(store: ExtractionStore) -> None:
    po_number = uuid.uuid4().hex[:10]
    save(store, po_number=po_number)

    found = store.list(ExtractionQuery(po_number=po_number))

    assert len(found) == 1
    assert found[0]["po_number"] == po_number


def test_lookup_by_item_code_returns_one_row_per_order(store: ExtractionStore) -> None:
    po_number = uuid.uuid4().hex[:10]
    duplicated = {
        **order(po_number),
        "items": [
            {**order(po_number)["items"][0]},
            {**order(po_number)["items"][0], "customer_number": "CT-9002"},
        ],
    }
    request_id, _ = save(store, po_number=po_number, data=duplicated)

    found = [
        row
        for row in store.list(ExtractionQuery(toto_number="TX703AR", limit=500))
        if row["request_id"] == request_id
    ]

    assert len(found) == 1, "two matching lines must not yield two rows"


def test_the_review_queue_can_be_listed(store: ExtractionStore) -> None:
    request_id, _ = save(store, validation_status="needs_review")

    found = [
        row
        for row in store.list(ExtractionQuery(validation_status="needs_review", limit=500))
        if row["request_id"] == request_id
    ]

    assert len(found) == 1


def test_counting_ignores_paging(store: ExtractionStore) -> None:
    po_number = uuid.uuid4().hex[:10]
    save(store, po_number=po_number)
    save(store, po_number=po_number)

    query = ExtractionQuery(po_number=po_number, limit=1)

    assert store.count(query) == 2
    assert len(store.list(query)) == 1


def test_an_unparseable_date_still_stores_the_row(store: ExtractionStore) -> None:
    """Records that failed validation are the ones most worth keeping."""
    po_number = uuid.uuid4().hex[:10]
    broken = {**order(po_number), "po_date": "2026/06/05"}

    request_id, _ = save(store, po_number=po_number, data=broken, validation_status="needs_review")

    found = store.get(request_id)
    assert found["po_date"] is None
    assert found["data"]["po_date"] == "2026/06/05"


def test_the_pool_reports_itself_ready(pool: DatabasePool) -> None:
    assert pool.check() is True
