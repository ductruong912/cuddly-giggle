"""Requests the API must turn away before they occupy an OCR slot."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from api.application import app


def test_the_expected_routes_are_registered() -> None:
    paths = {getattr(route, "path", None) for route in app.routes}

    assert {"/healthz", "/v1/extract/local", "/v1/extract/online", "/v1/doc/ocr"} <= paths


def test_healthz_reports_stage_occupancy(api: Any) -> None:
    async def body(client):
        return await client.get("/healthz")

    response = api(body)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["stages"]["ocr"]["max_concurrency"] == 2


def test_the_worker_pool_is_sized_from_the_stage_limits(api: Any) -> None:
    """Threads must outnumber the slots that use them, or stages starve."""

    async def body(client):
        from anyio import to_thread

        await client.get("/healthz")
        return to_thread.current_default_thread_limiter().total_tokens

    assert api(body) == 10, "OCR_MAX_CONCURRENCY + LLM_MAX_CONCURRENCY + 4"


def test_an_unaccepted_content_type_is_refused(api: Any) -> None:
    async def body(client):
        return await client.post(
            "/v1/extract/local", content=b"x", headers={"content-type": "application/xml"}
        )

    assert api(body).status_code == 415


def test_the_online_route_requires_multipart(api: Any) -> None:
    async def body(client):
        return await client.post(
            "/v1/extract/online", content=b"{}", headers={"content-type": "application/json"}
        )

    assert api(body).status_code == 415


def test_an_unsupported_file_type_is_refused(api: Any) -> None:
    async def body(client):
        return await client.post(
            "/v1/extract/local",
            files={"file": ("payload.exe", b"binary", "application/octet-stream")},
        )

    assert api(body).status_code == 400


def test_json_without_a_markdown_key_is_refused(api: Any) -> None:
    async def body(client):
        return await client.post("/v1/extract/local", json={"not_markdown": "x"})

    assert api(body).status_code == 400


def test_an_oversized_upload_is_refused(api: Any) -> None:
    """Rejected while streaming, so an over-cap file is never written whole."""

    async def body(client):
        return await client.post(
            "/v1/extract/local",
            files={"file": ("big.pdf", b"P" * 9000, "application/pdf")},
        )

    assert api(body).status_code == 413


def test_a_rejected_upload_leaves_no_temp_file(api: Any) -> None:
    async def body(client):
        await client.post(
            "/v1/extract/local",
            files={"file": ("big.pdf", b"P" * 9000, "application/pdf")},
        )
        staging = Path(os.environ["DOC_TEMP_DIR"])
        return sorted(staging.glob("*")) if staging.is_dir() else []

    assert api(body) == []


@pytest.mark.parametrize("route", ["/v1/extract/local", "/v1/extract/online"])
def test_a_missing_file_field_is_refused(api: Any, route: str) -> None:
    async def body(client):
        return await client.post(route, files={"wrong_field": ("a.pdf", b"x", "application/pdf")})

    assert api(body).status_code == 400
