"""Pool construction and credential handling — no server required."""
from __future__ import annotations

import dataclasses

import pytest

from config.config import Settings, mask_database_url, settings
from services.persistence import DatabasePool, DatabaseUnavailable


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

    with pytest.raises(DatabaseUnavailable, match="not open"):
        with pool.connection():
            pass


def test_an_unopened_pool_is_not_ready() -> None:
    pool = DatabasePool(configured("postgresql://u:p@127.0.0.1:5432/db"))

    assert pool.is_open is False
    assert pool.check() is False


def test_closing_an_unopened_pool_is_safe() -> None:
    DatabasePool(configured("postgresql://u:p@127.0.0.1:5432/db")).close()


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


def test_the_pool_is_built_the_way_the_driver_expects() -> None:
    """Guards against drift in the psycopg_pool constructor signature."""
    psycopg_pool = pytest.importorskip("psycopg_pool")
    import inspect

    accepted = set(inspect.signature(psycopg_pool.ConnectionPool.__init__).parameters)

    assert {"conninfo", "open", "min_size", "max_size", "kwargs", "name"} <= accepted
    assert "wait" in inspect.signature(psycopg_pool.ConnectionPool.open).parameters
    assert hasattr(psycopg_pool.ConnectionPool, "check")


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
