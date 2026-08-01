"""Admission control for the expensive pipeline stages.

The service runs one OCR pipeline against one GPU, so unbounded concurrency does
not buy throughput — it only grows an invisible queue and starves the event loop.
Each stage therefore gets a bounded semaphore, and requests that cannot get a slot
in time are rejected with a retryable error instead of piling up.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import time
from typing import Any, TypeVar

# pyrefly: ignore [missing-import]
from starlette.concurrency import run_in_threadpool

from config.config import Settings, settings


logger = logging.getLogger(__name__)

T = TypeVar("T")

# Below this, queueing is normal scheduling jitter and not worth a log line.
_QUEUE_LOG_THRESHOLD_SECONDS = 0.5


class StageSaturated(RuntimeError):
    """Every slot for a pipeline stage was busy for longer than the wait budget."""

    def __init__(self, stage: str, wait_timeout_seconds: float) -> None:
        super().__init__(
            f"The {stage} stage is at capacity; no slot became free within "
            f"{wait_timeout_seconds:g}s. Retry shortly."
        )
        self.stage = stage
        self.wait_timeout_seconds = wait_timeout_seconds


class StageTimedOut(RuntimeError):
    """A stage held its slot longer than the work was allowed to take."""

    def __init__(self, stage: str, execution_timeout_seconds: float) -> None:
        super().__init__(
            f"The {stage} stage did not finish within {execution_timeout_seconds:g}s "
            "and was abandoned."
        )
        self.stage = stage
        self.execution_timeout_seconds = execution_timeout_seconds


class StageLimiter:
    """Run blocking stage work in the threadpool behind a bounded async semaphore.

    Waiting happens on the semaphore rather than inside a worker thread, so queued
    requests hold no thread and the event loop stays free to serve health checks
    and accept new connections while the GPU is busy.
    """

    def __init__(
        self,
        name: str,
        max_concurrency: int,
        wait_timeout_seconds: float,
        execution_timeout_seconds: float,
    ) -> None:
        self.name = name
        self.max_concurrency = max_concurrency
        self.wait_timeout_seconds = wait_timeout_seconds
        self.execution_timeout_seconds = execution_timeout_seconds
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._in_flight = 0
        self._abandoned = 0

    @property
    def in_flight(self) -> int:
        """Number of requests currently occupying a slot."""
        return self._in_flight

    @property
    def abandoned(self) -> int:
        """Slots held by work that timed out and has not yet returned.

        Non-zero means a dependency is wedged: the stage is running below its
        configured capacity until those calls unblock, which usually only
        happens when the dependency is restarted.
        """
        return self._abandoned

    async def run(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Acquire a slot, then run ``func`` in a worker thread under a time budget.

        Raises:
            StageSaturated: no slot became free within the configured wait budget.
            StageTimedOut: the work exceeded the execution budget.
        """
        await self._acquire()
        self._in_flight += 1
        # Shielded so the timeout abandons the *wait*, not the work: a worker
        # thread cannot be cancelled, and pretending otherwise would release a
        # slot whose thread is still running and admit more work than capacity.
        task = asyncio.ensure_future(run_in_threadpool(func, *args, **kwargs))
        try:
            result = await asyncio.wait_for(
                asyncio.shield(task), timeout=self.execution_timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            self._abandon(task)
            logger.error(
                "stage=%s abandoned a request after %.0fs; the slot stays held until the "
                "call returns (abandoned=%s of %s slots)",
                self.name,
                self.execution_timeout_seconds,
                self._abandoned,
                self.max_concurrency,
            )
            raise StageTimedOut(self.name, self.execution_timeout_seconds) from exc
        except asyncio.CancelledError:
            # The caller went away (client disconnect). The thread carries on, so
            # the slot is not ours to give back yet.
            self._abandon(task)
            raise
        except BaseException:
            self._settle()
            raise
        self._settle()
        return result

    def _abandon(self, task: "asyncio.Future[Any]") -> None:
        """Keep the slot booked until the orphaned call actually returns."""
        self._abandoned += 1
        task.add_done_callback(self._on_abandoned_done)

    def _on_abandoned_done(self, task: "asyncio.Future[Any]") -> None:
        self._abandoned -= 1
        self._settle()
        if not task.cancelled() and task.exception() is not None:
            logger.warning(
                "stage=%s abandoned call finally returned an error: %s",
                self.name,
                task.exception(),
            )
        else:
            logger.info("stage=%s abandoned call returned; slot recovered", self.name)

    def _settle(self) -> None:
        self._in_flight -= 1
        self._semaphore.release()

    async def _acquire(self) -> None:
        wait_start = time.perf_counter()
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self.wait_timeout_seconds)
        except asyncio.TimeoutError as exc:
            logger.warning(
                "stage=%s rejected a request after waiting %.3fs for one of %s slots",
                self.name,
                time.perf_counter() - wait_start,
                self.max_concurrency,
            )
            raise StageSaturated(self.name, self.wait_timeout_seconds) from exc

        # Report the wait only once it is known and real; the in-flight count read
        # before acquiring lags by a scheduling step and would be misleading.
        waited = time.perf_counter() - wait_start
        if waited >= _QUEUE_LOG_THRESHOLD_SECONDS:
            logger.warning(
                "stage=%s queued a request for %.2fs; all %s slots were busy",
                self.name,
                waited,
                self.max_concurrency,
            )


class PipelineLimiters:
    """The stage limiters shared by every request, sized from configuration."""

    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings
        self.ocr = StageLimiter(
            "ocr",
            app_settings.ocr_max_concurrency,
            app_settings.stage_queue_timeout_seconds,
            app_settings.ocr_execution_timeout_seconds,
        )
        self.llm = StageLimiter(
            "llm",
            app_settings.llm_max_concurrency,
            app_settings.stage_queue_timeout_seconds,
            app_settings.llm_execution_timeout_seconds,
        )
        # File staging and artifact writes are short and disk-bound; they get a
        # generous slot count so they never queue behind OCR work.
        self.io = StageLimiter(
            "io",
            max(4, app_settings.ocr_max_concurrency * 2),
            app_settings.stage_queue_timeout_seconds,
            app_settings.io_execution_timeout_seconds,
        )

    @property
    def stages(self) -> tuple[StageLimiter, ...]:
        return (self.ocr, self.llm, self.io)

    @property
    def degraded_stages(self) -> list[str]:
        """Stages running below capacity because work timed out and never returned."""
        return [limiter.name for limiter in self.stages if limiter.abandoned]

    def snapshot(self) -> dict[str, dict[str, int]]:
        """Current occupancy per stage, for the health endpoint."""
        return {
            limiter.name: {
                "in_flight": limiter.in_flight,
                "max_concurrency": limiter.max_concurrency,
                "abandoned": limiter.abandoned,
            }
            for limiter in self.stages
        }


def apply_thread_pool_size(app_settings: Settings = settings) -> int:
    """Resize anyio's worker-thread pool to match the configured stage limits.

    Must be called from inside the running event loop (anyio stores the limiter in
    a run-scoped variable). Returns the applied size.
    """
    # pyrefly: ignore [missing-import]
    from anyio import to_thread

    size = app_settings.resolved_thread_pool_size
    to_thread.current_default_thread_limiter().total_tokens = size
    logger.info(
        "worker threads=%s ocr_slots=%s llm_slots=%s queue_timeout=%.0fs",
        size,
        app_settings.ocr_max_concurrency,
        app_settings.llm_max_concurrency,
        app_settings.stage_queue_timeout_seconds,
    )
    return size
