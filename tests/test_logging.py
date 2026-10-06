"""Quiet logging must preserve failures and document request visibility."""
from __future__ import annotations

import logging
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from config import config


@pytest.mark.parametrize(
    ("method", "path", "status", "visible"),
    [
        ("GET", "/assets/app.js", 304, False),
        ("HEAD", "/assets/font.woff2?v=1", 200, False),
        ("GET", "/healthz", 200, False),
        ("GET", "/readyz?probe=1", 200, False),
        ("GET", "/readyz", 503, True),
        ("GET", "/assets/missing.js", 404, True),
        ("POST", "/v1/doc/ocr/result?include_preview=true", 200, True),
        ("GET", "/v1/ui/config", 200, True),
        ("GET", "/", 200, True),
    ],
)
def test_quiet_access_keeps_errors_and_api_requests(monkeypatch, method, path, status, visible):
    monkeypatch.setattr(config, "settings", SimpleNamespace(quiet_third_party_logs=True))
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, "%s %s %s %s %s",
        ("127.0.0.1:1234", method, path, "1.1", status), None,
    )
    quiet_filter = config.QuietAccessLogFilter()
    assert quiet_filter.filter(record) is visible
    record.levelno = logging.WARNING
    assert quiet_filter.filter(record)
    record.levelno = logging.INFO
    monkeypatch.setattr(config, "settings", SimpleNamespace(quiet_third_party_logs=False))
    assert quiet_filter.filter(record)


def test_quiet_http_logging_survives_root_handler(monkeypatch, capture_logs):
    monkeypatch.setattr(config, "settings", SimpleNamespace(quiet_third_party_logs=True))
    monkeypatch.setitem(sys.modules, "paddlex.utils", SimpleNamespace(logging=Mock()))
    for name in ("httpx", "httpcore"):
        monkeypatch.setattr(logging.getLogger(name), "level", logging.NOTSET)
    with capture_logs("httpx", logging.INFO) as logs:
        config.configure_third_party_logging()
        # Simulate model-loading probes and the individual OCR block calls.
        with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as client:
            client.get("http://localhost/health")
            client.post("http://localhost/v1/chat/completions")
        logging.getLogger("httpx").warning("transport warning")
        logging.getLogger("httpx").error("transport error")
    assert "HTTP Request" not in logs.getvalue()
    assert "transport warning" in logs.getvalue()
    assert "transport error" in logs.getvalue()


def test_quiet_disabled_leaves_library_levels_unchanged(monkeypatch):
    monkeypatch.setattr(config, "settings", SimpleNamespace(quiet_third_party_logs=False))
    for name in ("httpx", "httpcore"):
        monkeypatch.setattr(logging.getLogger(name), "level", logging.INFO)
    config.configure_third_party_logging()
    assert logging.getLogger("httpx").level == logging.INFO
    assert logging.getLogger("httpcore").level == logging.INFO
