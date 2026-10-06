"""OCR must wait for model readiness even after llama.cpp binds its port."""
from __future__ import annotations

from unittest.mock import Mock

import httpx
import pytest

from services.llama import server


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
