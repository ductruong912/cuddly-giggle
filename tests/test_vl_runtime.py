"""The VL runtime must notice when llama.cpp dies instead of latching on ready.

The previous behaviour set ``_ready = True`` once and never re-checked, so a
crashed backend took every later request down until the API was restarted.
"""
from __future__ import annotations

import pytest

from services.vl_runtime import VLRuntimeManager


class FakeProcess:
    """Stands in for a llama-server subprocess."""

    def __init__(self) -> None:
        self.exit_code: int | None = None
        self.stopped = False

    def poll(self) -> int | None:
        return self.exit_code

    def die(self, code: int = 1) -> None:
        self.exit_code = code


class RuntimeHarness:
    """Builds managers whose start/stop/warmup calls are all observable."""

    def __init__(self, *, probe_result: bool = True) -> None:
        self.processes: list[FakeProcess] = []
        self.stopped: list[FakeProcess] = []
        self.warmups = 0
        self.probe_result = probe_result

    def configure(self) -> FakeProcess:
        process = FakeProcess()
        self.processes.append(process)
        return process

    def warmup(self) -> None:
        self.warmups += 1

    def stop(self, process: FakeProcess) -> None:
        process.stopped = True
        self.stopped.append(process)

    def probe(self) -> bool:
        return self.probe_result

    def manager(self, *, owns_process: bool = True) -> VLRuntimeManager:
        return VLRuntimeManager(
            configure_runtime=self.configure if owns_process else (lambda: None),
            warmup=self.warmup,
            stop_runtime=self.stop,
            probe=self.probe,
        )


def test_the_runtime_starts_once_for_repeated_calls() -> None:
    harness = RuntimeHarness()
    manager = harness.manager()

    assert manager.was_started is False
    manager.shutdown()
    assert manager.is_ready is False
    manager.ensure_ready()
    manager.ensure_ready()
    manager.ensure_ready()

    assert len(harness.processes) == 1
    assert harness.warmups == 1
    assert manager.is_ready


def test_a_dead_process_is_restarted_on_next_use() -> None:
    """The fix: the next request revives the backend instead of failing forever."""
    harness = RuntimeHarness()
    manager = harness.manager()
    manager.ensure_ready()
    harness.processes[0].die()
    assert manager.is_ready is False
    assert manager.was_started is True

    manager.ensure_ready()

    assert len(harness.processes) == 2
    assert harness.warmups == 2
    assert manager.is_ready


def test_restart_replaces_a_process_that_is_still_alive() -> None:
    """A wedged llama.cpp does not exit; killing it is what frees blocked calls."""
    harness = RuntimeHarness()
    manager = harness.manager()
    manager.ensure_ready()
    original = harness.processes[0]

    manager.restart()

    assert original.stopped is True
    assert len(harness.processes) == 2
    assert manager.is_ready


def test_shutdown_stops_a_process_this_manager_started() -> None:
    harness = RuntimeHarness()
    manager = harness.manager()
    manager.ensure_ready()

    manager.shutdown()

    assert harness.processes[0].stopped is True
    assert manager.is_ready is False
    assert manager.was_started is False


def test_an_external_server_is_judged_by_the_probe() -> None:
    """docker-compose runs llama.cpp in its own container; there is no process to poll."""
    harness = RuntimeHarness(probe_result=True)
    manager = harness.manager(owns_process=False)
    manager.ensure_ready()

    assert manager.is_ready is True

    harness.probe_result = False
    assert manager.is_ready is False


@pytest.mark.parametrize("probe_result", [True, False])
def test_the_probe_does_not_override_a_live_owned_process(probe_result: bool) -> None:
    """When this process owns the server, its exit status is the authority."""
    harness = RuntimeHarness(probe_result=probe_result)
    manager = harness.manager()
    manager.ensure_ready()

    assert manager.is_ready is True
