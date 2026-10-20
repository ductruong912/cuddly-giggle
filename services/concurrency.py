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
import threading
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


class _StageCall:
    """Track real thread completion independently of its cancellable async task."""

    def __init__(
        self,
        limiter: StageLimiter,
        cleanup: Callable[[], None] | None,
        cleanup_on_success: bool,
    ) -> None:
        self.limiter = limiter
        self.cleanup = cleanup
        self.cleanup_on_success = cleanup_on_success
        self.loop = asyncio.get_running_loop()
        self._lock = threading.Lock()
        self.started = False
        self.finished = False
        self.abandoned = False
        self.cleaned = False
        self.settled = False
        self.counted_abandoned = False
        self.error: BaseException | None = None

    def run(self, func: Callable[..., T], args: tuple[Any, ...], kwargs: dict[str, Any]) -> T:
        with self._lock:
            if self.finished:
                # Its async task was cancelled before execution. A thread that
                # arrives late must not touch the resource already discarded.
                return None  # type: ignore[return-value]
            self.started = True
        try:
            return func(*args, **kwargs)
        except BaseException as exc:
            self.error = exc
            raise
        finally:
            with self._lock:
                self.finished = True
                should_clean = self.cleanup_on_success or self.error is not None or self.abandoned
            try:
                if should_clean:
                    self._cleanup_once()
            finally:
                self._notify_finished()

    def abandon(self) -> None:
        with self._lock:
            self.abandoned = True
            finished = self.finished
        # Even a completed staging result needs cleanup if delivery was cancelled.
        if finished:
            self._cleanup_once()

    def on_task_done(self, task: "asyncio.Future[Any]") -> None:
        if not task.cancelled() and task.exception() is None:
            return
        with self._lock:
            if self.started or self.finished:
                return
            self.finished = True
        try:
            self._cleanup_once()
        finally:
            self._notify_finished()

    def _cleanup_once(self) -> None:
        with self._lock:
            if self.cleaned:
                return
            self.cleaned = True
        self.limiter._cleanup(self.cleanup)

    def _notify_finished(self) -> None:
        try:
            self.loop.call_soon_threadsafe(self.limiter._on_call_finished, self)
        except RuntimeError:
            # A closed loop has no live semaphore waiters. Cleanup still runs in
            # the thread during shutdown, and the dead limiter can settle safely.
            if not self.loop.is_closed():
                raise
            self.limiter._on_call_finished(self)


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
        return await self._run(func, args, kwargs)

    async def run_with_cleanup(
        self,
        func: Callable[..., T],
        *args: Any,
        cleanup: Callable[[], None],
        cleanup_on_success: bool = True,
        **kwargs: Any,
    ) -> T:
        """Own a resource until blocking work really finishes, including abandonment.

        Cleanup also runs when admission fails before a worker starts. Set
        ``cleanup_on_success=False`` when a successful return transfers the
        resource to the caller, as with staging an upload.
        The synchronous cleanup hook can run in the worker or the caller thread.
        """
        return await self._run(
            func, args, kwargs, cleanup=cleanup, cleanup_on_success=cleanup_on_success
        )

    async def _run(
        self,
        func: Callable[..., T],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        *,
        cleanup: Callable[[], None] | None = None,
        cleanup_on_success: bool = True,
    ) -> T:
        try:
            await self._acquire()
        except BaseException:
            self._cleanup(cleanup)
            raise
        self._in_flight += 1
        # Shielded so the timeout abandons the *wait*, not the work: a worker
        # thread cannot be cancelled, and pretending otherwise would release a
        # slot whose thread is still running and admit more work than capacity.
        call = _StageCall(self, cleanup, cleanup_on_success)
        task = asyncio.ensure_future(run_in_threadpool(call.run, func, args, kwargs))
        task.add_done_callback(call.on_task_done)
        try:
            result = await asyncio.wait_for(
                asyncio.shield(task), timeout=self.execution_timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            if task.done() and not task.cancelled() and task.exception() is exc:
                # A dependency can raise TimeoutError itself. That is finished
                # work, not an execution-budget timeout with a live worker.
                raise
            self._abandon(call)
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
            self._abandon(call)
            raise
        return result

    def _abandon(self, call: _StageCall) -> None:
        """Keep the slot booked until the orphaned call actually returns."""
        call.abandon()
        if not call.settled:
            call.counted_abandoned = True
            self._abandoned += 1

    def _on_call_finished(self, call: _StageCall) -> None:
        if call.settled:
            return
        call.settled = True
        self._settle()
        if not call.counted_abandoned:
            return
        self._abandoned -= 1
        if call.error is not None:
            logger.warning(
                "stage=%s abandoned call finally returned an error: %s",
                self.name,
                call.error,
            )
        else:
            logger.info("stage=%s abandoned call returned; slot recovered", self.name)

    def _cleanup(self, cleanup: Callable[[], None] | None) -> None:
        if cleanup is not None:
            try:
                cleanup()
            except Exception:
                logger.exception("stage=%s resource cleanup failed", self.name)

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
