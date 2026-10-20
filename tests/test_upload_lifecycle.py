"""Regression checks for input ownership while abandoned workers keep running."""
from __future__ import annotations

import asyncio
import io
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from starlette.datastructures import UploadFile
from starlette.requests import Request

from api.errors import UploadTooLarge
from api.routes import _extract_upload, _parse_ocr_upload
from api.uploads import UploadStager
from core.domain.schemas import ParseDecision, ParseResponse
from services.concurrency import StageLimiter, StageSaturated, StageTimedOut
from services.document_extraction import DocumentExtractionService


def _settlement_event(monkeypatch: pytest.MonkeyPatch, limiter: StageLimiter) -> asyncio.Event:
    settled = asyncio.Event()
    original = limiter._on_call_finished

    def notify(call):
        original(call)
        if limiter.in_flight == 0:
            settled.set()

    monkeypatch.setattr(limiter, "_on_call_finished", notify)
    return settled


def _limiter(name: str, *, timeout: float = 5) -> StageLimiter:
    return StageLimiter(name, 1, 0.05, timeout)


def _stager(limiter: StageLimiter, root: Path) -> UploadStager:
    return UploadStager(limiter, SimpleNamespace(temp_dir=root, max_upload_bytes=4096))


def _upload() -> UploadFile:
    return UploadFile(io.BytesIO(b"synthetic input"), filename="same.pdf")


async def _stage(stager: UploadStager, upload: UploadFile):
    return await stager.stage(
        upload, allowed_suffixes=frozenset({".pdf"}), unsupported_message="unsupported"
    )


def _response(request_id: str = "req_lifecycle") -> ParseResponse:
    return ParseResponse(
        request_id=request_id,
        decision=ParseDecision(reason="test"),
        pages=[], blocks=[], tables=[], reading_order=[], markdown="# synthetic",
    )


@pytest.mark.parametrize("failure", ["timeout", "cancel"])
def test_abandoned_staging_cleans_files_created_after_the_caller_leaves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    async def body() -> None:
        limiter = _limiter("io", timeout=0.2 if failure == "timeout" else 5)
        settled = _settlement_event(monkeypatch, limiter)
        stager = _stager(limiter, tmp_path)
        started, cleaned = asyncio.Event(), asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        write = stager._write_to_disk
        discard = stager._discard_path

        def delayed_write(source, destination):
            loop.call_soon_threadsafe(started.set)
            assert release.wait(5), "test did not release the staging worker"
            return write(source, destination)

        def notify_cleanup(path):
            discard(path)
            loop.call_soon_threadsafe(cleaned.set)

        monkeypatch.setattr(stager, "_write_to_disk", delayed_write)
        monkeypatch.setattr(stager, "_discard_path", notify_cleanup)
        request = asyncio.create_task(_stage(stager, _upload()))
        try:
            await asyncio.wait_for(started.wait(), 5)
            if failure == "cancel":
                request.cancel()
                expected = asyncio.CancelledError
            else:
                expected = StageTimedOut
            with pytest.raises(expected):
                await request
            assert not list(tmp_path.iterdir()), "the worker has not created a file yet"
            assert limiter.in_flight == limiter.abandoned == 1
            with pytest.raises(StageSaturated):
                await limiter.run(lambda: None)
        finally:
            release.set()
        await asyncio.wait_for(cleaned.wait(), 5)
        await asyncio.wait_for(settled.wait(), 5)
        assert not list(tmp_path.iterdir()), "late creation must not leave an orphan"
        assert limiter.in_flight == limiter.abandoned == 0

    asyncio.run(body())


def test_staging_result_cancelled_at_delivery_still_cleans_the_completed_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def body() -> None:
        limiter = _limiter("io")
        settled = _settlement_event(monkeypatch, limiter)
        stager = _stager(limiter, tmp_path)
        original_wait_for = asyncio.wait_for
        cleaned = asyncio.Event()
        loop = asyncio.get_running_loop()
        discard = stager._discard_path

        async def cancel_at_delivery(awaitable, timeout):
            result = await original_wait_for(awaitable, timeout)
            if isinstance(awaitable, asyncio.Future):
                # The worker has completed, but the caller never receives its result.
                assert len(list(tmp_path.iterdir())) == 1
                raise asyncio.CancelledError
            return result

        def notify_cleanup(path):
            discard(path)
            loop.call_soon_threadsafe(cleaned.set)

        monkeypatch.setattr(stager, "_discard_path", notify_cleanup)
        monkeypatch.setattr(asyncio, "wait_for", cancel_at_delivery)
        with pytest.raises(asyncio.CancelledError):
            await _stage(stager, _upload())
        await original_wait_for(cleaned.wait(), 5)
        await original_wait_for(settled.wait(), 5)
        assert not list(tmp_path.iterdir())
        assert limiter.in_flight == limiter.abandoned == 0

    asyncio.run(body())


def test_successful_staging_transfers_file_ownership_to_the_caller(tmp_path: Path) -> None:
    async def body() -> None:
        limiter = _limiter("io")
        stager = _stager(limiter, tmp_path)
        staged = await _stage(stager, _upload())
        assert staged.path.read_bytes() == b"synthetic input"
        assert limiter.in_flight == 0
        stager.discard(staged)
        assert not staged.path.exists()

    asyncio.run(body())


def test_staging_worker_error_removes_its_partial_file(tmp_path: Path) -> None:
    async def body() -> None:
        limiter = _limiter("io")
        stager = _stager(limiter, tmp_path)
        oversized = UploadFile(io.BytesIO(b"x" * 4097), filename="big.pdf")
        with pytest.raises(UploadTooLarge):
            await _stage(stager, oversized)
        assert not list(tmp_path.iterdir())
        assert limiter.in_flight == limiter.abandoned == 0

    asyncio.run(body())


@pytest.mark.parametrize("failure", ["timeout", "cancel"])
@pytest.mark.parametrize("route", ["ocr", "preview", "extraction"])
def test_parse_input_survives_until_abandoned_worker_reads_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, valid_order: dict, failure: str, route: str
) -> None:
    async def body() -> None:
        ocr = _limiter("ocr", timeout=0.2 if failure == "timeout" else 5)
        settled = _settlement_event(monkeypatch, ocr)
        limiters = SimpleNamespace(ocr=ocr, io=_limiter("io"), llm=_limiter("llm"))
        stager = _stager(limiters.io, tmp_path)
        loop = asyncio.get_running_loop()
        started, cleaned = asyncio.Event(), asyncio.Event()
        release = threading.Event()
        observed = []
        discard = stager.discard

        class Parser:
            def parse(self, input_path, *, request_id=None):
                observed.append(Path(input_path))
                loop.call_soon_threadsafe(started.set)
                assert release.wait(5), "test did not release the parse worker"
                observed.append(Path(input_path).read_bytes())
                return _response(request_id or "req_lifecycle")

        class Extractor:
            def extract(self, parse_response, *, correction=None):
                return valid_order

        def notify_cleanup(staged):
            discard(staged)
            loop.call_soon_threadsafe(cleaned.set)

        monkeypatch.setattr(stager, "discard", notify_cleanup)
        if route == "extraction":
            service = DocumentExtractionService(Parser(), Extractor(), limiters, route_label="test")
            pending = _extract_upload(
                service, stager, _upload(), allowed_suffixes=frozenset({".pdf"}),
                unsupported_message="unsupported",
            )
        else:
            request = Request({"type": "http", "headers": [(b"content-type", b"multipart/form-data")]})
            pending = _parse_ocr_upload(
                request, _upload(), Parser(), stager, limiters, include_preview=route == "preview"
            )
        request_task = asyncio.create_task(pending)
        try:
            await asyncio.wait_for(started.wait(), 5)
            if failure == "cancel":
                request_task.cancel()
                expected = asyncio.CancelledError
            else:
                expected = StageTimedOut
            with pytest.raises(expected):
                await request_task
            assert observed[0].exists(), "a timed-out caller must not delete a worker's input"
            assert not cleaned.is_set()
            assert ocr.in_flight == ocr.abandoned == 1
            with pytest.raises(StageSaturated):
                await ocr.run(lambda: None)
        finally:
            release.set()
        await asyncio.wait_for(cleaned.wait(), 5)
        await asyncio.wait_for(settled.wait(), 5)
        assert observed[1] == b"synthetic input"
        assert not observed[0].exists()
        assert ocr.in_flight == ocr.abandoned == 0

    asyncio.run(body())


def test_shutdown_cancellation_preserves_input_until_the_thread_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "shutdown.pdf"
    path.write_bytes(b"synthetic input")
    limiter = _limiter("ocr", timeout=0.2)
    release, finished, cleaned, settled = (threading.Event() for _ in range(4))
    cleanup_observations = []
    original_finish = limiter._on_call_finished

    def notify_finish(call):
        original_finish(call)
        settled.set()

    monkeypatch.setattr(limiter, "_on_call_finished", notify_finish)

    def work():
        assert release.wait(5)
        assert path.read_bytes() == b"synthetic input"
        finished.set()

    def cleanup():
        cleanup_observations.append(finished.is_set())
        path.unlink()
        cleaned.set()

    async def body():
        with pytest.raises(StageTimedOut):
            await limiter.run_with_cleanup(work, cleanup=cleanup)

    try:
        # asyncio.run cancels the inner run_in_threadpool task at shutdown even
        # though the actual AnyIO thread is still blocked.
        asyncio.run(body())
        assert path.exists()
        assert not cleaned.is_set()
        assert not finished.is_set()
        assert limiter.in_flight == limiter.abandoned == 1
    finally:
        release.set()
    assert cleaned.wait(5)
    assert settled.wait(5)
    assert cleanup_observations == [True]
    assert not path.exists()
    assert limiter.in_flight == limiter.abandoned == 0


def test_startup_cleanup_removes_only_owned_staged_files(tmp_path: Path) -> None:
    import uuid
    from types import SimpleNamespace

    from api.uploads import cleanup_temp_dir

    staged = tmp_path / f"{uuid.uuid4().hex}.pdf"
    unrelated = tmp_path / "keep.txt"
    nested = tmp_path / f"{uuid.uuid4().hex}.pdf"
    nested.mkdir()
    nested_file = nested / "keep.txt"
    staged.write_bytes(b"stale staged input")
    unrelated.write_text("keep", encoding="utf-8")
    nested_file.write_bytes(b"keep nested content")

    removed = cleanup_temp_dir(SimpleNamespace(temp_dir=tmp_path))

    assert removed == 1
    assert not staged.exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert nested_file.read_bytes() == b"keep nested content"


@pytest.mark.parametrize("protected_name", [".", "outputs", "models"])
def test_startup_cleanup_refuses_a_protected_application_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, protected_name: str
) -> None:
    from types import SimpleNamespace

    import api.uploads as uploads

    fake_repo = tmp_path / "repo"
    (fake_repo / "api").mkdir(parents=True)
    (fake_repo / "api" / "uploads.py").touch()
    monkeypatch.setattr(uploads, "__file__", str(fake_repo / "api" / "uploads.py"))

    protected_root = fake_repo if protected_name == "." else fake_repo / protected_name
    protected_root.mkdir(exist_ok=True)
    sentinel = protected_root / "must-keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    with pytest.raises(ValueError):
        uploads.cleanup_temp_dir(SimpleNamespace(temp_dir=protected_root))

    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_temp_root_validation_rejects_filesystem_and_shared_temp_roots() -> None:
    import tempfile
    from types import SimpleNamespace

    from api.uploads import _safe_temp_root

    with pytest.raises(ValueError):
        _safe_temp_root(SimpleNamespace(temp_dir=Path(Path.cwd().anchor)))
    with pytest.raises(ValueError):
        _safe_temp_root(SimpleNamespace(temp_dir=Path(tempfile.gettempdir())))


def test_temp_root_validation_rejects_overlap_with_external_configured_paths(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from api.uploads import _safe_temp_root

    external_data = tmp_path / "application-data"
    configured_output = external_data / "outputs"
    staging = configured_output / "staging"

    with pytest.raises(ValueError, match="overlap application data"):
        _safe_temp_root(
            SimpleNamespace(temp_dir=staging, parse_output_dir=configured_output)
        )


def test_temp_root_validation_resolves_relative_paths() -> None:
    import uuid
    from types import SimpleNamespace

    from api.uploads import _safe_temp_root

    relative_path = Path(f"cuddly-giggle-test-{uuid.uuid4().hex}")

    assert _safe_temp_root(SimpleNamespace(temp_dir=relative_path)) == (
        Path.cwd() / relative_path
    ).resolve()


def test_startup_cleanup_rejects_symlinked_temp_directory(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    import api.uploads as uploads

    target = tmp_path / "target"
    target.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    staging = alias / "staging"
    staging.mkdir()

    with pytest.raises(ValueError, match="symbolic links"):
        uploads.cleanup_temp_dir(SimpleNamespace(temp_dir=staging))


def test_startup_cleanup_skips_symlink_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uuid
    from types import SimpleNamespace

    import api.uploads as uploads

    external_target = tmp_path.parent / f"external-{uuid.uuid4().hex}.pdf"
    symlink_entry = tmp_path / f"{uuid.uuid4().hex}.pdf"
    external_target.write_bytes(b"external data")
    symlink_entry.write_bytes(b"simulated link entry")
    original_is_symlink = Path.is_symlink

    def is_symlink(path: Path) -> bool:
        return path == symlink_entry or original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", is_symlink)

    assert uploads.cleanup_temp_dir(SimpleNamespace(temp_dir=tmp_path)) == 0
    assert symlink_entry.read_bytes() == b"simulated link entry"
    assert external_target.read_bytes() == b"external data"


@pytest.mark.parametrize("failure", ["timeout", "inner_cancel"])
def test_thread_token_queue_does_not_confuse_async_task_completion_with_worker_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from anyio import to_thread
    import services.concurrency as concurrency

    async def body() -> None:
        thread_tokens = to_thread.current_default_thread_limiter()
        original_tokens = thread_tokens.total_tokens
        thread_tokens.total_tokens = 1
        release = threading.Event()
        loop = asyncio.get_running_loop()
        holding, submitted = asyncio.Event(), asyncio.Event()
        path = tmp_path / "queued-token.pdf"
        path.write_bytes(b"queued input")
        limiter = _limiter("ocr", timeout=0.2 if failure == "timeout" else 5)
        settled = _settlement_event(monkeypatch, limiter)
        original_run = concurrency.run_in_threadpool
        captured = []
        observed = []

        def occupy_token():
            loop.call_soon_threadsafe(holding.set)
            assert release.wait(5)

        async def watch_submission(func, *args, **kwargs):
            captured.append((asyncio.current_task(), func, args, kwargs))
            submitted.set()
            return await original_run(func, *args, **kwargs)

        def work():
            observed.append(path.read_bytes())

        holder = asyncio.create_task(original_run(occupy_token))
        try:
            await asyncio.wait_for(holding.wait(), 5)
            monkeypatch.setattr(concurrency, "run_in_threadpool", watch_submission)
            pending = asyncio.create_task(limiter.run_with_cleanup(work, cleanup=path.unlink))
            await asyncio.wait_for(submitted.wait(), 5)
            if failure == "inner_cancel":
                captured[0][0].cancel()
                expected = asyncio.CancelledError
            else:
                expected = StageTimedOut
            with pytest.raises(expected):
                await pending
            assert not observed, "there is no thread token for the worker yet"
            if failure == "timeout":
                assert path.exists()
                assert limiter.in_flight == limiter.abandoned == 1
            else:
                await asyncio.wait_for(settled.wait(), 5)
                assert not path.exists(), "cancelled unstarted work can discard immediately"
                assert limiter.in_flight == limiter.abandoned == 0
        finally:
            release.set()
            await holder
            thread_tokens.total_tokens = original_tokens
        await asyncio.wait_for(settled.wait(), 5)
        if failure == "timeout":
            assert observed == [b"queued input"]
        else:
            # Model the narrow race where dispatch reaches the wrapper after its
            # async task was cancelled. It must skip the already discarded input.
            _, wrapper, args, kwargs = captured[0]
            await original_run(wrapper, *args, **kwargs)
            assert not observed
        assert not path.exists()
        assert limiter.in_flight == limiter.abandoned == 0

    asyncio.run(body())


@pytest.mark.parametrize("failure", ["saturated", "cancel"])
def test_input_waiting_for_parse_admission_is_cleaned_without_starting_a_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    async def body() -> None:
        limiter = _limiter("ocr")
        if failure == "cancel":
            limiter.wait_timeout_seconds = 5
        path = tmp_path / "queued.pdf"
        path.write_bytes(b"queued input")
        acquired = asyncio.Event()
        original_acquire = limiter._acquire

        async def notify_acquire():
            acquired.set()
            await original_acquire()

        monkeypatch.setattr(limiter, "_acquire", notify_acquire)
        await limiter._semaphore.acquire()  # Occupied by other work, with no thread to leak.
        ran = []
        pending = asyncio.create_task(
            limiter.run_with_cleanup(lambda: ran.append(True), cleanup=path.unlink)
        )
        await acquired.wait()
        if failure == "cancel":
            pending.cancel()
            expected = asyncio.CancelledError
        else:
            expected = StageSaturated
        with pytest.raises(expected):
            await pending
        assert not path.exists()
        assert not ran
        assert limiter.in_flight == limiter.abandoned == 0
        assert limiter._semaphore.locked(), "admission failure must not release another slot"
        limiter._semaphore.release()

    asyncio.run(body())


@pytest.mark.parametrize("failure", [None, RuntimeError, TimeoutError])
def test_cleanup_runs_once_after_finished_work_and_never_masks_its_error(failure) -> None:
    async def body() -> None:
        limiter = _limiter("ocr")
        calls = []
        original = failure("worker failure") if failure else None

        def work():
            if original:
                raise original
            return 7

        def cleanup():
            calls.append(True)
            raise OSError("synthetic cleanup failure")

        if original:
            with pytest.raises(failure) as raised:
                await limiter.run_with_cleanup(work, cleanup=cleanup)
            assert raised.value is original
        else:
            assert await limiter.run_with_cleanup(work, cleanup=cleanup) == 7
        assert calls == [True]
        assert limiter.in_flight == limiter.abandoned == 0
        assert await limiter.run(lambda: 8) == 8

    asyncio.run(body())
