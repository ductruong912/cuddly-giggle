"""Shared test bootstrap.

``config.config`` builds its ``settings`` object at import time, so the
environment has to be set before any test module imports it. pytest imports
conftest first, which is why this happens at module scope rather than in a
fixture.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[1]
_TEST_TEMP_ROOT = Path(tempfile.mkdtemp(prefix="cuddly-giggle-tests-"))

# `load_dotenv(..., override=False)` leaves these in place, so a developer's .env
# cannot change what the suite measures.
os.environ.update(
    OPENAI_API_KEY="test-key-never-used",
    DATABASE_URL="",
    PARSE_OUTPUT_DIR=str(_TEST_TEMP_ROOT / "outputs"),
    DOC_TEMP_DIR=str(_TEST_TEMP_ROOT / "staging"),
    LLM_SELF_HEAL_MAX_RETRIES="2",
    PO_LINE_TOTAL_TOLERANCE_RATIO="0.01",
    OCR_MAX_CONCURRENCY="2",
    LLM_MAX_CONCURRENCY="4",
    STAGE_QUEUE_TIMEOUT_SECONDS="2",
    MAX_UPLOAD_BYTES="4096",
    PDF_MAX_PAGES="3",
    RATE_LIMIT_DEFAULT="10000/minute",
    RATE_LIMIT_EXTRACT="10000/minute",
    WARMUP_MODELS_ON_STARTUP="false",
    PADDLEOCR_VL_USE_GGUF="false",
)

import asyncio  # noqa: E402
from collections.abc import Awaitable, Callable, Iterator  # noqa: E402
from contextlib import contextmanager  # noqa: E402
import io  # noqa: E402
import logging  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402

from core.domain.schemas import ParseDecision, ParseResponse  # noqa: E402


VALID_ORDER = {
    "po_number": "215497",
    "po_date": "05-06-2026",
    "items": [
        {
            "toto_number": "TX703AR",
            "customer_number": "CT-9001",
            "quantity": 4,
            "unit_price": 1250000,
            "extension": 5000000,
        }
    ],
}


@pytest.fixture
def valid_order() -> dict:
    """A purchase order that satisfies every deterministic check."""
    return {**VALID_ORDER, "items": [dict(VALID_ORDER["items"][0])]}


@pytest.fixture
def parse_response() -> ParseResponse:
    """A minimal parse result, for driving extraction without an OCR engine."""
    return ParseResponse(
        request_id="req_test",
        decision=ParseDecision(reason="test fixture"),
        pages=[],
        blocks=[],
        tables=[],
        reading_order=[],
        markdown="# test document",
    )


@pytest.fixture
def temp_root() -> Path:
    """The directory this run writes artifacts and staged uploads into."""
    return _TEST_TEMP_ROOT


@pytest.fixture
def capture_logs() -> Callable[..., Any]:
    """Capture records from a first-party logger.

    pytest's ``caplog`` attaches to the root logger, but ``configure_app_logging``
    sets ``propagate = False`` on the app loggers — paddlex installs its own root
    handler, so propagating would print every line twice. Once anything has
    imported the app, ``caplog`` therefore sees nothing from them. This attaches
    to the named logger directly instead.
    """

    @contextmanager
    def capture(logger_name: str, level: int = logging.WARNING) -> Iterator[io.StringIO]:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(level)
        target = logging.getLogger(logger_name)
        previous_level = target.level
        target.addHandler(handler)
        target.setLevel(level)
        try:
            yield stream
        finally:
            target.removeHandler(handler)
            target.setLevel(previous_level)

    return capture


@pytest.fixture
def api() -> Callable[[Callable[[Any], Awaitable[Any]]], Any]:
    """Run an async body against the app with its lifespan active.

    The stage limiters hold semaphores, so each test gets its own set: a
    semaphore that outlived its event loop would carry stale waiters into the
    next test. ``reset_singletons`` is what makes that cheap.
    """
    # Imported lazily so tests that never touch HTTP do not build the app.
    import httpx

    from api.application import app
    from api.dependencies import reset_singletons

    def run(body: Callable[[Any], Awaitable[Any]]) -> Any:
        async def runner() -> Any:
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    return await body(client)

        reset_singletons()
        try:
            return asyncio.run(runner())
        finally:
            app.dependency_overrides.clear()
            reset_singletons()

    return run
