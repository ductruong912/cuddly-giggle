"""The property the concurrency work exists for: many requests, one busy GPU.

The stand-in parser blocks a real worker thread the way OCR does, so these
measure the actual threading behaviour rather than a simulation of it.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from api.application import app
from api.dependencies import get_local_extraction_service, get_pipeline_limiters
from core.domain.schemas import ParseDecision, ParseResponse
from services.document_extraction import DocumentExtractionService


class BlockingParser:
    """Occupies a worker thread for a fixed time, recording peak concurrency."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.in_flight = 0
        self.peak_in_flight = 0

    def parse(self, input_path: str, options: object = None, *, request_id: str | None = None):
        del input_path, options
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            time.sleep(self.seconds)
            return ParseResponse(
                request_id=request_id or "req_test",
                decision=ParseDecision(reason="blocking stub"),
                pages=[],
                blocks=[],
                tables=[],
                reading_order=[],
                markdown="# stub\n\nbody",
            )
        finally:
            self.in_flight -= 1


class StubExtractor:
    """Returns a record that satisfies every deterministic check."""

    def __init__(self, order: dict) -> None:
        self.order = order

    def extract(self, parse_response: ParseResponse, *, correction: str | None = None) -> dict:
        del parse_response, correction
        return self.order


def install_pipeline(parser: BlockingParser, order: dict) -> None:
    """Point the local route at the stand-in parser for one test."""
    app.dependency_overrides[get_local_extraction_service] = lambda: DocumentExtractionService(
        parser, StubExtractor(order), get_pipeline_limiters(), route_label="test"
    )


async def upload(client: Any, index: int):
    return await client.post(
        "/v1/extract/local",
        files={"file": (f"doc{index}.pdf", b"%PDF-1.4 stub", "application/pdf")},
    )


def test_concurrent_uploads_all_succeed(api: Any, valid_order: dict) -> None:
    parser = BlockingParser(seconds=0.4)

    async def body(client):
        install_pipeline(parser, valid_order)
        return await asyncio.gather(*(upload(client, index) for index in range(6)))

    responses = api(body)

    assert [r.status_code for r in responses] == [200] * 6


def test_the_ocr_stage_never_exceeds_its_slots(api: Any, valid_order: dict) -> None:
    parser = BlockingParser(seconds=0.4)

    async def body(client):
        install_pipeline(parser, valid_order)
        await asyncio.gather(*(upload(client, index) for index in range(6)))

    api(body)

    assert parser.peak_in_flight == 2, "OCR_MAX_CONCURRENCY is 2: not more, and not serialised"


def test_the_event_loop_stays_responsive_while_ocr_runs(api: Any, valid_order: dict) -> None:
    """The bug this replaced: OCR ran on the event loop and froze every route."""
    parser = BlockingParser(seconds=0.5)

    async def body(client):
        install_pipeline(parser, valid_order)
        uploads = asyncio.gather(*(upload(client, index) for index in range(6)))
        await asyncio.sleep(0.15)

        started = time.perf_counter()
        health = await client.get("/healthz")
        latency = time.perf_counter() - started

        await uploads
        assert health.status_code == 200
        return latency

    assert api(body) < 0.15


def test_queued_work_is_batched_by_the_slot_count(api: Any, valid_order: dict) -> None:
    parser = BlockingParser(seconds=0.4)

    async def body(client):
        install_pipeline(parser, valid_order)
        started = time.perf_counter()
        await asyncio.gather(*(upload(client, index) for index in range(6)))
        return time.perf_counter() - started

    elapsed = api(body)

    # 6 jobs through 2 slots is 3 batches: comfortably over 2 batches, under 6.
    assert 0.8 < elapsed < 2.0, f"took {elapsed:.2f}s"


def test_a_saturated_stage_sheds_load(api: Any, valid_order: dict) -> None:
    """Over the queue timeout, requests are refused rather than queued forever."""
    parser = BlockingParser(seconds=2.5)

    async def body(client):
        install_pipeline(parser, valid_order)
        return await asyncio.gather(*(upload(client, index) for index in range(6)))

    responses = api(body)
    codes = [r.status_code for r in responses]

    assert 503 in codes, f"nothing was shed: {codes}"
    assert 200 in codes, f"nothing got through: {codes}"


def test_a_shed_request_says_when_to_retry(api: Any, valid_order: dict) -> None:
    parser = BlockingParser(seconds=2.5)

    async def body(client):
        install_pipeline(parser, valid_order)
        return await asyncio.gather(*(upload(client, index) for index in range(6)))

    rejected = [r for r in api(body) if r.status_code == 503]

    assert rejected, "the test needs at least one shed request"
    assert all("retry-after" in r.headers for r in rejected)


def test_the_response_carries_its_validation_verdict(api: Any, valid_order: dict) -> None:
    parser = BlockingParser(seconds=0.05)

    async def body(client):
        install_pipeline(parser, valid_order)
        return await upload(client, 0)

    payload = api(body).json()

    assert payload["validation"]["status"] == "valid"
    assert payload["validation"]["attempts"] == 1
    assert payload["validation"]["healed"] is False


def test_a_needs_review_record_still_returns_200(api: Any, valid_order: dict) -> None:
    """There is no review queue, so the verdict travels in the response body."""
    shifted = {**valid_order, "items": [dict(valid_order["items"][0])]}
    shifted["items"][0]["extension"] = 500000
    parser = BlockingParser(seconds=0.05)

    async def body(client):
        install_pipeline(parser, shifted)
        return await upload(client, 0)

    response = api(body)

    assert response.status_code == 200
    payload = response.json()
    assert payload["validation"]["status"] == "needs_review"
    assert payload["validation"]["attempts"] == 3
    assert payload["data"] == shifted, "the record is returned for a human to judge"
    assert any("line total mismatch" in issue["message"] for issue in payload["validation"]["issues"])
