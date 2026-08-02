"""A wedged dependency must not take the service down permanently.

Before the execution timeout existed, a hung OCR call held its slot forever.
With OCR_MAX_CONCURRENCY at 2, two hung calls meant every later request was
refused until someone restarted the process.
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from services.concurrency import StageLimiter, StageSaturated, StageTimedOut


def limiter(
    *, slots: int = 1, wait: float = 0.2, execution: float = 0.15
) -> StageLimiter:
    return StageLimiter("test", slots, wait, execution)


async def settle(stage: StageLimiter, *, timeout: float = 5.0) -> None:
    """Wait for abandoned work to return and hand its slot back."""
    deadline = asyncio.get_running_loop().time() + timeout
    while stage.abandoned and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)


def test_work_inside_the_budget_is_unaffected() -> None:
    stage = limiter(execution=2.0)

    async def body() -> str:
        return await stage.run(lambda: "done")

    assert asyncio.run(body()) == "done"


def test_overrunning_work_fails_the_request() -> None:
    stage = limiter()
    release = threading.Event()

    async def body() -> None:
        with pytest.raises(StageTimedOut, match="did not finish"):
            await stage.run(release.wait, 5)
        release.set()
        await settle(stage)

    asyncio.run(body())


def test_an_abandoned_slot_is_not_handed_back_early() -> None:
    """The thread is still running, so releasing the slot would over-admit work."""
    stage = limiter(slots=1)
    release = threading.Event()

    async def body() -> None:
        with pytest.raises(StageTimedOut):
            await stage.run(release.wait, 5)

        assert stage.abandoned == 1
        assert stage.in_flight == 1, "the slot is still occupied by the running thread"

        with pytest.raises(StageSaturated):
            await stage.run(lambda: "should not get in")

        release.set()
        await settle(stage)

    asyncio.run(body())


def test_the_slot_returns_once_the_call_finally_completes() -> None:
    """Restarting the wedged dependency makes the call return; capacity recovers."""
    stage = limiter(slots=1)
    release = threading.Event()

    async def body() -> str:
        with pytest.raises(StageTimedOut):
            await stage.run(release.wait, 5)

        release.set()  # stands in for the dependency being restarted
        await settle(stage)

        assert stage.abandoned == 0
        assert stage.in_flight == 0
        return await stage.run(lambda: "recovered")

    assert asyncio.run(body()) == "recovered"


def test_a_failing_call_releases_its_slot() -> None:
    """An ordinary error is not an abandonment; the slot must come straight back."""
    stage = limiter(slots=1)

    def explode() -> None:
        raise ValueError("boom")

    async def body() -> str:
        with pytest.raises(ValueError, match="boom"):
            await stage.run(explode)

        assert (stage.in_flight, stage.abandoned) == (0, 0)
        return await stage.run(lambda: "still working")

    assert asyncio.run(body()) == "still working"


def test_the_stage_reports_that_it_is_degraded() -> None:
    """Readiness depends on this: a held slot must be visible, not silent."""
    stage = limiter(slots=2)
    release = threading.Event()

    async def body() -> None:
        with pytest.raises(StageTimedOut):
            await stage.run(release.wait, 5)

        assert stage.abandoned == 1
        release.set()
        await settle(stage)
        assert stage.abandoned == 0

    asyncio.run(body())


def test_the_snapshot_exposes_abandoned_slots() -> None:
    from services.concurrency import PipelineLimiters

    from config.config import settings

    snapshot = PipelineLimiters(settings).snapshot()

    assert set(snapshot) == {"ocr", "llm", "io"}
    for stage_state in snapshot.values():
        assert set(stage_state) == {"in_flight", "max_concurrency", "abandoned"}


def test_degraded_stages_are_named() -> None:
    from services.concurrency import PipelineLimiters

    from config.config import settings

    limiters = PipelineLimiters(settings)
    release = threading.Event()

    async def body() -> None:
        assert limiters.degraded_stages == []

        # Force a timeout on the OCR stage specifically.
        limiters.ocr.execution_timeout_seconds = 0.1
        with pytest.raises(StageTimedOut):
            await limiters.ocr.run(release.wait, 5)

        assert limiters.degraded_stages == ["ocr"]
        release.set()
        await settle(limiters.ocr)
        assert limiters.degraded_stages == []

    asyncio.run(body())
