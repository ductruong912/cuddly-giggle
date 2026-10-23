"""Stage limits, llama bootstrap and lifecycle, artifact retention and dependency consistency."""
from __future__ import annotations

import asyncio
import dataclasses
import os
from pathlib import Path
import shutil
import threading
import time
from unittest.mock import Mock
import zipfile

import httpx
import pytest

from config.config import Settings, settings
from services.concurrency import StageLimiter, StageSaturated, StageTimedOut
from services.llama import bootstrap, server
from services.retention import SECONDS_PER_DAY, ArtifactRetentionSweeper
from services.vl_runtime import VLRuntimeManager


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


def test_an_abandoned_slot_is_not_handed_back_early() -> None:
    """The thread is still running, so releasing the slot would over-admit work."""
    stage = limiter(slots=1)
    release = threading.Event()

    async def body() -> str:
        with pytest.raises(StageTimedOut, match="did not finish"):
            await stage.run(release.wait, 5)

        assert stage.abandoned == 1
        assert stage.in_flight == 1, "the slot is still occupied by the running thread"

        with pytest.raises(StageSaturated):
            await stage.run(lambda: "should not get in")

        release.set()
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


@pytest.mark.parametrize(
    ("status", "payload", "ready"),
    [(503, {"error": {"message": "Loading model"}}, False),
     (200, {"status": "ok"}, True), (200, {"status": "ok", "slots_idle": 1}, True),
     (200, {"status": "loading"}, False), (200, [], False)],
)
def test_health_checks_model_readiness(monkeypatch, status, payload, ready) -> None:
    get = Mock(return_value=httpx.Response(status, json=payload))
    monkeypatch.setattr(server.httpx, "get", get)

    assert server.is_llama_server_ready("127.0.0.1", 8080) is ready
    get.assert_called_once_with(
        "http://127.0.0.1:8080/health", timeout=0.25, trust_env=False
    )


@pytest.mark.parametrize("failure", [httpx.ConnectError("offline"), ValueError("bad JSON")])
def test_unreachable_or_invalid_health_is_not_ready(monkeypatch, failure) -> None:
    monkeypatch.setattr(server.httpx, "get", Mock(side_effect=failure))
    assert not server.is_llama_server_ready("127.0.0.1", 8080)


@pytest.fixture
def startup_clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(server.time, "monotonic", lambda: now[0])

    def sleep(seconds):
        now[0] += seconds

    monkeypatch.setattr(server.time, "sleep", sleep)
    return now


@pytest.mark.parametrize("already_listening", [False, True])
def test_startup_waits_through_loading_model(
    monkeypatch, tmp_path, startup_clock, already_listening
) -> None:
    paths = [tmp_path / name for name in ("llama-server.exe", "model.gguf", "mmproj.gguf")]
    for path in paths:
        path.touch()
    config = server.LlamaServerConfig(
        executable_path=paths[0], model_path=paths[1], mmproj_path=paths[2]
    )
    health = Mock(side_effect=[
        httpx.Response(503, json={"error": {"message": "Loading model"}}),
        httpx.Response(503, json={"error": {"message": "Loading model"}}),
        httpx.Response(200, json={"status": "ok"}),
    ])
    monkeypatch.setattr(server.httpx, "get", health)
    process = Mock()
    popen = Mock(return_value=process)

    result = server.start_llama_server_if_needed(
        config, port_check=lambda *_: already_listening, popen=popen
    )

    assert health.call_count == 3
    assert startup_clock[0] == 0.5
    assert result is (None if already_listening else process)
    assert popen.call_count == (0 if already_listening else 1)
    process.terminate.assert_not_called()


@pytest.mark.parametrize("already_listening", [False, True])
def test_startup_timeout_stops_only_an_owned_process(
    monkeypatch, tmp_path, startup_clock, already_listening
) -> None:
    paths = [tmp_path / name for name in ("llama-server.exe", "model.gguf", "mmproj.gguf")]
    for path in paths:
        path.touch()
    config = server.LlamaServerConfig(
        executable_path=paths[0], model_path=paths[1], mmproj_path=paths[2],
        startup_timeout_seconds=0.4,
    )
    monkeypatch.setattr(
        server.httpx, "get", Mock(return_value=httpx.Response(503, json={"error": {}}))
    )
    process = Mock()
    process.poll.return_value = None
    popen = Mock(return_value=process)

    with pytest.raises(RuntimeError, match="did not become ready"):
        server.start_llama_server_if_needed(
            config, port_check=lambda *_: already_listening, popen=popen
        )

    assert startup_clock[0] == 0.4
    assert process.terminate.call_count == (0 if already_listening else 1)
    assert popen.call_count == (0 if already_listening else 1)


FLAVOR = "win-cuda-12.4-x64"
RELEASES_URL = f"{bootstrap.LLAMA_CPP_RELEASES_API}?per_page={bootstrap.LLAMA_CPP_RELEASE_SEARCH_LIMIT}"


def release(tag: str, *assets: str, draft: bool = False) -> dict:
    """A GitHub release entry; the numbered builds are published as prereleases."""
    base = f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}"
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": tag.startswith("b"),
        "assets": [{"name": name, "browser_download_url": f"{base}/{name}"} for name in assets],
    }


def full_build(tag: str, *, draft: bool = False) -> dict:
    return release(tag, f"llama-{tag}-bin-{FLAVOR}.zip", f"cudart-llama-bin-{FLAVOR}.zip", draft=draft)


class FakeReleasesApi(bootstrap.HttpDownloader):
    def __init__(self, payload: object) -> None:
        super().__init__()
        self.payload = payload
        self.requested: list[str] = []

    def get_json(self, url: str) -> object:
        self.requested.append(url)
        return self.payload


def test_the_newest_release_with_the_flavors_assets_is_chosen() -> None:
    """/releases/latest now names a tag whose only asset is nightly-tag.txt."""
    api = FakeReleasesApi([
        full_build("b11838", draft=True),
        release("v0.7.0", "nightly-tag.txt"),
        release("b11837", f"llama-b11837-bin-{FLAVOR}.zip"),  # CUDA runtime not uploaded yet
        full_build("b11836"),
        full_build("b11835"),
    ])

    urls = bootstrap.resolve_latest_llama_cpp_release_urls(flavor=FLAVOR, downloader=api)

    base = "https://github.com/ggml-org/llama.cpp/releases/download/b11836"
    assert urls == [f"{base}/llama-b11836-bin-{FLAVOR}.zip", f"{base}/cudart-llama-bin-{FLAVOR}.zip"]
    assert api.requested == [RELEASES_URL]


def test_no_release_with_the_flavor_points_at_the_override() -> None:
    api = FakeReleasesApi([release("v0.7.0", "nightly-tag.txt"), release("b11836", "llama-b11836-bin-ubuntu-x64.zip")])

    with pytest.raises(RuntimeError, match=f"{FLAVOR}.*LLAMA_CPP_RELEASE_URL"):
        bootstrap.resolve_latest_llama_cpp_release_urls(flavor=FLAVOR, downloader=api)


@pytest.mark.parametrize("override", ["", "https://example.test/llama.zip"])
def test_the_release_url_setting_overrides_the_lookup(tmp_path: Path, override: str) -> None:
    from scripts import setup_llama_cpp

    app_settings = dataclasses.replace(
        settings,
        llama_cpp_dir=str(tmp_path / "llama"),
        llama_cpp_models_dir=str(tmp_path / "models"),
        llama_cpp_release_url=override,
    )
    resolve = Mock(return_value=["https://example.test/resolved.zip"])
    install = Mock()

    setup_llama_cpp.main(app_settings=app_settings, bootstrap=install, resolve_release_urls=resolve)

    config = install.call_args.kwargs["config"]
    assert resolve.called is not bool(override)
    assert config.llama_release_url == override
    assert config.llama_release_urls == (() if override else ("https://example.test/resolved.zip",))


def write_zip(path: Path, names: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, b"binary")
    return path


class LocalDownloader(bootstrap.HttpDownloader):
    """Serves URLs from local files, so the real extract-and-install path runs."""

    def __init__(self, files: dict[str, Path]) -> None:
        super().__init__(attempts=1)
        self.files = files
        self.requested: list[str] = []

    def download_file(self, url: str, destination: Path) -> None:
        self.requested.append(url)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.files[url], destination)


def bootstrap_from(tmp_path: Path, binaries: list[str]) -> tuple[LocalDownloader, bootstrap.LlamaBootstrapConfig]:
    """A binary zip holding ``binaries`` plus a CUDA runtime zip that holds only cudart DLLs."""
    served = tmp_path / "served"
    binary_url = f"https://example.test/llama-b11836-bin-{FLAVOR}.zip"
    runtime_url = f"https://example.test/cudart-llama-bin-{FLAVOR}.zip"
    model = served / "model.gguf"
    files = {
        binary_url: write_zip(served / "llama.zip", binaries),
        runtime_url: write_zip(served / "cudart.zip", ["cudart64_12.dll", "cublas64_12.dll"]),
    }
    config = bootstrap.LlamaBootstrapConfig(
        llama_dir=tmp_path / "llama",
        models_dir=tmp_path / "models",
        llama_release_urls=(binary_url, runtime_url),
        min_model_bytes=1,
    )
    for artifact in bootstrap.default_model_artifacts(config.models_dir):
        files[artifact.url] = model
    model.write_bytes(b"gguf")
    return LocalDownloader(files), config


def test_the_cuda_runtime_zip_installs_alongside_the_binaries(tmp_path: Path) -> None:
    """The cudart zip never carries llama-server.exe; only the combined install is checked."""
    downloader, config = bootstrap_from(tmp_path, list(bootstrap.REQUIRED_LLAMA_FILES))

    result = bootstrap.bootstrap_llama_cpp(config=config, downloader=downloader)

    assert result.downloaded_llama_cpp is True
    assert bootstrap.is_llama_cpp_ready(config.llama_dir)
    assert (config.llama_dir / "cudart64_12.dll").is_file()
    assert result.downloaded_models == ["PaddleOCR-VL-1.6-GGUF.gguf", "PaddleOCR-VL-1.6-GGUF-mmproj.gguf"]


def test_files_missing_from_every_archive_stop_before_the_models(tmp_path: Path) -> None:
    binaries = [name for name in bootstrap.REQUIRED_LLAMA_FILES if name != "ggml.dll"]
    downloader, config = bootstrap_from(tmp_path, binaries)

    with pytest.raises(RuntimeError, match=r"did not provide required files: ggml\.dll$"):
        bootstrap.bootstrap_llama_cpp(config=config, downloader=downloader)

    assert downloader.requested == list(config.llama_release_urls)


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
    assert manager.was_started is True, "distinguishes 'never started' from 'died'"

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


def test_shutdown_is_safe_when_nothing_was_started() -> None:
    manager = RuntimeHarness().manager()

    manager.shutdown()

    assert manager.is_ready is False


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


@pytest.fixture
def outputs(tmp_path: Path) -> Path:
    directory = tmp_path / "outputs"
    directory.mkdir()
    return directory


def configured(outputs: Path, *, retention_days: int) -> Settings:
    return dataclasses.replace(
        settings,
        parse_output_dir=str(outputs),
        parse_output_retention_days=retention_days,
    )


def artifact_dir(outputs: Path, name: str, *, age_days: float) -> Path:
    """Create a saved-artifact directory with a backdated modification time."""
    directory = outputs / name
    directory.mkdir()
    (directory / f"{name}.json").write_text("{}", encoding="utf-8")
    stamp = time.time() - age_days * SECONDS_PER_DAY
    os.utime(directory, (stamp, stamp))
    return directory


def test_only_the_expired_ones_go(outputs: Path) -> None:
    keep = artifact_dir(outputs, "keep", age_days=2)
    drop = artifact_dir(outputs, "drop", age_days=40)

    result = ArtifactRetentionSweeper(configured(outputs, retention_days=14)).sweep()

    assert keep.exists()
    assert not drop.exists()
    assert (result.removed, result.scanned) == (1, 2)


def test_a_boundary_age_is_kept(outputs: Path) -> None:
    """Exactly at the window is inside it; only strictly older is removed."""
    edge = artifact_dir(outputs, "edge", age_days=13.9)

    ArtifactRetentionSweeper(configured(outputs, retention_days=14)).sweep()

    assert edge.exists()


def test_retention_can_be_disabled(outputs: Path) -> None:
    ancient = artifact_dir(outputs, "ancient", age_days=9999)
    sweeper = ArtifactRetentionSweeper(configured(outputs, retention_days=0))

    result = sweeper.sweep()

    assert sweeper.enabled is False
    assert ancient.exists()
    assert result.removed == 0


def test_a_missing_output_directory_is_not_an_error(tmp_path: Path) -> None:
    """The sweep runs on a timer and must never raise into the event loop."""
    sweeper = ArtifactRetentionSweeper(configured(tmp_path / "absent", retention_days=7))

    assert sweeper.sweep().removed == 0


def test_loose_files_are_left_alone(outputs: Path) -> None:
    """Only per-document directories are managed; anything else is not ours."""
    stray = outputs / "notes.txt"
    stray.write_text("x", encoding="utf-8")
    stamp = time.time() - 9999 * SECONDS_PER_DAY
    os.utime(stray, (stamp, stamp))

    result = ArtifactRetentionSweeper(configured(outputs, retention_days=1)).sweep()

    assert stray.exists()
    assert result.scanned == 0


def test_an_undeletable_directory_is_counted_not_raised(
    outputs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One locked directory must not stop the rest of the sweep."""
    artifact_dir(outputs, "locked", age_days=99)
    artifact_dir(outputs, "deletable", age_days=99)

    real_rmtree = __import__("shutil").rmtree

    def selective_rmtree(path, *args, **kwargs):
        if Path(path).name == "locked":
            raise OSError("in use by another process")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr("services.retention.shutil.rmtree", selective_rmtree)

    result = ArtifactRetentionSweeper(configured(outputs, retention_days=1)).sweep()

    assert (result.removed, result.failed) == (1, 1)
    assert (outputs / "locked").exists()


REPO_ROOT = Path(__file__).resolve().parents[1]
FULL = REPO_ROOT / "requirements.txt"
CI = REPO_ROOT / "requirements-ci.txt"


def read_requirements(path: Path) -> dict[str, str]:
    """Map distribution name to its full specifier, ignoring comments and flags."""
    entries: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        name = line.split("==")[0].split(">=")[0].split("[")[0].strip()
        entries[name.lower()] = line
    return entries


@pytest.fixture(scope="module")
def full_requirements() -> dict[str, str]:
    return read_requirements(FULL)


@pytest.fixture(scope="module")
def ci_requirements() -> dict[str, str]:
    return read_requirements(CI)


def test_ci_requirements_match_full_requirements(
    ci_requirements: dict, full_requirements: dict
) -> None:
    unknown = set(ci_requirements) - set(full_requirements)

    assert not unknown, f"requirements-ci.txt pins packages absent from requirements.txt: {unknown}"
    drifted = {
        name: (specifier, full_requirements[name])
        for name, specifier in ci_requirements.items()
        if specifier != full_requirements[name]
    }

    assert not drifted, f"pins differ between requirements files: {drifted}"


def test_the_suites_own_dependencies_are_pinned(ci_requirements: dict) -> None:
    """Whatever the tests import directly has to be installable in CI."""
    for required in ("pytest", "httpx", "fastapi", "pydantic", "pymupdf"):
        assert required in ci_requirements, f"{required} is missing from requirements-ci.txt"


def test_the_heavy_extras_are_excluded(ci_requirements: dict) -> None:
    """Pulling these into CI would need CUDA and a custom index."""
    for excluded in ("paddlepaddle-gpu", "paddleocr", "paddlex", "onnxruntime"):
        assert excluded not in ci_requirements
