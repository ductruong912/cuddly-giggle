"""Keep saved artifacts from filling the disk.

One directory is written per document, and nothing ever removed it. On a service
that runs for months that is unbounded growth, and a full disk turns every
subsequent write into a 500 — a slow failure that looks like an application bug.

The sweep runs on a timer rather than only at startup, because a healthy service
does not restart often enough for startup cleanup to matter.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
import logging
from pathlib import Path
import shutil
import time

from config.config import Settings, settings


logger = logging.getLogger(__name__)

SECONDS_PER_DAY = 86400


@dataclass(frozen=True)
class SweepResult:
    """What one pass removed."""

    removed: int
    failed: int
    scanned: int


class ArtifactRetentionSweeper:
    """Delete saved artifact directories older than the retention window."""

    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings

    @property
    def enabled(self) -> bool:
        """False when PARSE_OUTPUT_RETENTION_DAYS is 0, meaning keep everything."""
        return self.settings.parse_output_retention_days > 0

    def sweep(self) -> SweepResult:
        """Remove expired artifact directories. Never raises: this must not break a request."""
        root = Path(self.settings.parse_output_dir)
        if not self.enabled or not root.is_dir():
            return SweepResult(removed=0, failed=0, scanned=0)

        cutoff = time.time() - self.settings.parse_output_retention_days * SECONDS_PER_DAY
        removed = failed = scanned = 0
        for entry in self._candidates(root):
            scanned += 1
            try:
                if entry.stat().st_mtime >= cutoff:
                    continue
                shutil.rmtree(entry)
                removed += 1
            except OSError:
                failed += 1
                logger.exception("could not remove expired artifact directory %s", entry)

        if removed or failed:
            logger.info(
                "artifact sweep: removed=%s failed=%s scanned=%s retention_days=%s",
                removed,
                failed,
                scanned,
                self.settings.parse_output_retention_days,
            )
        return SweepResult(removed=removed, failed=failed, scanned=scanned)

    @staticmethod
    def _candidates(root: Path) -> list[Path]:
        try:
            return [entry for entry in root.iterdir() if entry.is_dir()]
        except OSError:
            logger.exception("could not list the artifact directory %s", root)
            return []


@asynccontextmanager
async def artifact_retention_task(
    app_settings: Settings = settings,
) -> AsyncIterator[asyncio.Task[None] | None]:
    """Run the sweep on a timer for as long as the app is up.

    Yields ``None`` when retention is disabled, so the caller needs no special
    case for the "keep everything" configuration.
    """
    sweeper = ArtifactRetentionSweeper(app_settings)
    if not sweeper.enabled:
        logger.info("artifact retention is disabled (PARSE_OUTPUT_RETENTION_DAYS=0)")
        yield None
        return

    interval = app_settings.parse_output_sweep_minutes * 60
    logger.info(
        "artifact retention: keeping %s day(s), sweeping every %s minute(s)",
        app_settings.parse_output_retention_days,
        app_settings.parse_output_sweep_minutes,
    )
    task = asyncio.create_task(_sweep_forever(sweeper, interval), name="artifact-retention")
    try:
        yield task
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _sweep_forever(sweeper: ArtifactRetentionSweeper, interval_seconds: float) -> None:
    """Sweep immediately, then every interval, until cancelled."""
    while True:
        try:
            # Off the event loop: the sweep stats and deletes files.
            await asyncio.to_thread(sweeper.sweep)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A failing sweep must not kill the loop; the next pass may succeed.
            logger.exception("artifact retention sweep failed; will retry next interval")
        await asyncio.sleep(interval_seconds)
