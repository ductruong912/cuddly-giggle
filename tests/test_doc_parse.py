"""Tests for POST /v1/doc/parse (structured page geometry, blocks, bboxes, confidence)."""
from __future__ import annotations

from typing import Any

from api.application import app
from api.dependencies import get_orchestrator, get_settings
from config.config import Settings, settings
from core.domain.schemas import (
    Block,
    BlockType,
    ConfidenceSource,
    CoordinateSpace,
    PageGeometry,
    PageParseResult,
    PageVisualDTO,
    ParseDecision,
    ParseResponse,
    Point,
    Table,
    TableCell,
    to_document_parse_response,
)
from services.output import (
    get_page_visual_dir,
    get_page_visual_image_path,
    save_page_visual_image,
)
from services.retention import ArtifactRetentionSweeper


class DummyParser:
    def __init__(self, response: ParseResponse) -> None:
        self._response = response

    def parse(self, input_path: str, options: object = None, *, request_id: str | None = None) -> ParseResponse:
        del input_path, options, request_id
        return self._response


def test_doc_parse_route_is_registered() -> None:
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/v1/doc/parse" in paths


def test_to_document_parse_response_normalizes_bbox_and_confidence() -> None:
    geometry = PageGeometry(width=2000.0, height=1000.0, coordinate_space=CoordinateSpace.processed_image_pixels)
    block_ocr = Block(
        block_id="blk_ocr_1",
        type=BlockType.text,
        content="Invoice 123",
        bbox=[
            Point(x=200.0, y=100.0),
            Point(x=600.0, y=100.0),
            Point(x=600.0, y=200.0),
            Point(x=200.0, y=200.0),
        ],
        confidence=0.96,
        page_index=0,
        source_engine="paddleocr_vl",
    )
    block_native = Block(
        block_id="blk_nat_1",
        type=BlockType.text,
        content="Native Text",
        bbox=[],
        confidence=0.98,
        page_index=0,
        source_engine="pdf_text",
    )
    block_zero = Block(
        block_id="blk_zero",
        type=BlockType.other,
        content="",
        bbox=[],
        confidence=0.0,
        page_index=0,
        source_engine="paddleocr_vl",
    )
    table = Table(
        table_id="tbl_1",
        page_index=0,
        cells=[TableCell(row=0, col=0, text="Header", confidence=0.95)],
        confidence=0.95,
    )
    page = PageParseResult(
        page_index=0,
        geometry=geometry,
        blocks=[block_ocr, block_native, block_zero],
        tables=[table],
        reading_order=["blk_ocr_1", "blk_nat_1"],
        confidence=0.96,
        source_engine="paddleocr_vl",
    )
    raw_response = ParseResponse(
        request_id="req_test_parse",
        decision=ParseDecision(reason="Test parse"),
        pages=[page],
        blocks=[block_ocr, block_native, block_zero],
        tables=[table],
        reading_order=["blk_ocr_1", "blk_nat_1"],
        markdown="# Invoice 123",
        engine_name="paddleocr_vl",
    )

    doc_response = to_document_parse_response(raw_response)

    assert doc_response.request_id == "req_test_parse"
    assert doc_response.decision.reason == "Test parse"
    assert doc_response.engine_name == "paddleocr_vl"
    assert doc_response.markdown == "# Invoice 123"
    assert len(doc_response.pages) == 1

    p0 = doc_response.pages[0]
    assert p0.page_index == 0
    assert p0.geometry.width == 2000.0
    assert p0.geometry.height == 1000.0
    assert p0.geometry.coordinate_space == CoordinateSpace.processed_image_pixels

    # Check block 1 (OCR block with real engine score)
    b0 = p0.blocks[0]
    assert b0.block_id == "blk_ocr_1"
    assert b0.confidence == 0.96
    assert b0.confidence_source == ConfidenceSource.real_engine
    # Normalized bbox should be [200/2000, 100/1000] -> [0.1, 0.1]
    assert b0.bbox_normalized[0].x == 0.1
    assert b0.bbox_normalized[0].y == 0.1
    assert b0.bbox_normalized[1].x == 0.3
    assert b0.bbox_normalized[1].y == 0.1

    # Check block 2 (Native text block with synthesized score)
    b1 = p0.blocks[1]
    assert b1.block_id == "blk_nat_1"
    assert b1.confidence_source == ConfidenceSource.synthesized
    assert b1.bbox_normalized == []

    # Check block 3 (Zero confidence -> unknown)
    b2 = p0.blocks[2]
    assert b2.confidence_source == ConfidenceSource.unknown


def test_doc_parse_api_returns_structured_json(api: Any) -> None:
    geometry = PageGeometry(width=1000.0, height=2000.0, coordinate_space=CoordinateSpace.processed_image_pixels)
    block = Block(
        block_id="blk_1",
        type=BlockType.text,
        content="Sample Content",
        bbox=[Point(x=100.0, y=200.0), Point(x=500.0, y=200.0)],
        confidence=0.92,
        page_index=0,
        source_engine="paddleocr_vl",
    )
    fake_parse_response = ParseResponse(
        request_id="req_api_123",
        decision=ParseDecision(reason="OCR success"),
        pages=[
            PageParseResult(
                page_index=0,
                geometry=geometry,
                blocks=[block],
                tables=[],
                reading_order=["blk_1"],
                confidence=0.92,
                source_engine="paddleocr_vl",
            )
        ],
        blocks=[block],
        tables=[],
        reading_order=["blk_1"],
        markdown="# Sample Content",
        engine_name="paddleocr_vl",
    )

    async def body(client):
        app.dependency_overrides[get_orchestrator] = lambda: DummyParser(fake_parse_response)
        try:
            return await client.post(
                "/v1/doc/parse",
                files={"file": ("order.pdf", b"%PDF-1.4 dummy", "application/pdf")},
            )
        finally:
            app.dependency_overrides.pop(get_orchestrator, None)

    response = api(body)
    assert response.status_code == 200
    payload = response.json()

    assert payload["request_id"] == "req_api_123"
    assert payload["engine_name"] == "paddleocr_vl"
    assert payload["markdown"] == "# Sample Content"
    assert len(payload["pages"]) == 1

    page = payload["pages"][0]
    assert page["geometry"]["width"] == 1000.0
    assert page["geometry"]["height"] == 2000.0
    assert page["geometry"]["coordinate_space"] == "processed_image_pixels"

    assert len(page["blocks"]) == 1
    blk = page["blocks"][0]
    assert blk["block_id"] == "blk_1"
    assert blk["content"] == "Sample Content"
    assert blk["confidence"] == 0.92
    assert blk["confidence_source"] == "real_engine"
    assert len(blk["bbox"]) == 2
    assert blk["bbox"][0] == {"x": 100.0, "y": 200.0}
    # Normalized: x=100/1000=0.1, y=200/2000=0.1
    assert blk["bbox_normalized"][0] == {"x": 0.1, "y": 0.1}


def test_doc_parse_api_rejects_unsupported_suffix(api: Any) -> None:
    async def body(client):
        return await client.post(
            "/v1/doc/parse",
            files={"file": ("danger.exe", b"binary", "application/octet-stream")},
        )

    response = api(body)
    assert response.status_code == 400


def test_doc_parse_api_rejects_unsupported_content_type(api: Any) -> None:
    async def body(client):
        return await client.post(
            "/v1/doc/parse",
            content=b"raw binary",
            headers={"Content-Type": "application/x-binary"},
        )

    response = api(body)
    assert response.status_code == 415


def test_doc_parse_api_handles_multiple_pages(api: Any) -> None:
    page0 = PageParseResult(
        page_index=0,
        geometry=PageGeometry(width=1000.0, height=1500.0, coordinate_space=CoordinateSpace.processed_image_pixels),
        blocks=[
            Block(
                block_id="p0_b1",
                type=BlockType.title,
                content="Page 1 Title",
                bbox=[Point(x=50.0, y=50.0)],
                confidence=0.99,
                page_index=0,
                source_engine="paddleocr_vl",
            )
        ],
    )
    page1 = PageParseResult(
        page_index=1,
        geometry=PageGeometry(width=1000.0, height=1500.0, coordinate_space=CoordinateSpace.processed_image_pixels),
        blocks=[
            Block(
                block_id="p1_b1",
                type=BlockType.text,
                content="Page 2 Text",
                bbox=[Point(x=50.0, y=100.0)],
                confidence=0.88,
                page_index=1,
                source_engine="paddleocr_vl",
            )
        ],
    )
    multi_response = ParseResponse(
        request_id="req_multi",
        decision=ParseDecision(reason="Multi page parse"),
        pages=[page0, page1],
        blocks=page0.blocks + page1.blocks,
        tables=[],
        reading_order=["p0_b1", "p1_b1"],
        markdown="# Page 1\n\n# Page 2",
        engine_name="paddleocr_vl",
    )

    async def body(client):
        app.dependency_overrides[get_orchestrator] = lambda: DummyParser(multi_response)
        try:
            return await client.post(
                "/v1/doc/parse",
                files={"file": ("doc.pdf", b"%PDF-1.4 dummy", "application/pdf")},
            )
        finally:
            app.dependency_overrides.pop(get_orchestrator, None)

    response = api(body)
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["pages"]) == 2
    assert payload["pages"][0]["blocks"][0]["block_id"] == "p0_b1"
    assert payload["pages"][1]["blocks"][0]["block_id"] == "p1_b1"


def test_doc_ocr_still_returns_plain_markdown_without_regression(api: Any) -> None:
    fake_parse_response = ParseResponse(
        request_id="req_ocr_raw",
        decision=ParseDecision(reason="OCR Markdown"),
        pages=[],
        blocks=[],
        tables=[],
        reading_order=[],
        markdown="# RAW OCR MARKDOWN",
        engine_name="paddleocr_vl",
    )

    async def body(client):
        app.dependency_overrides[get_orchestrator] = lambda: DummyParser(fake_parse_response)
        try:
            return await client.post(
                "/v1/doc/ocr",
                files={"file": ("order.pdf", b"%PDF-1.4 dummy", "application/pdf")},
            )
        finally:
            app.dependency_overrides.pop(get_orchestrator, None)

    response = api(body)
    assert response.status_code == 200
    assert response.text == "# RAW OCR MARKDOWN"
    assert "text/markdown" in response.headers["content-type"]


def test_doc_parse_response_contains_visual_metadata() -> None:
    page = PageParseResult(
        page_index=0,
        geometry=PageGeometry(width=1000.0, height=1500.0, coordinate_space=CoordinateSpace.processed_image_pixels),
        blocks=[],
        visual=PageVisualDTO(available=True, kind="processed_page"),
    )
    raw_response = ParseResponse(
        request_id="req_vis_test",
        decision=ParseDecision(reason="Visual test"),
        pages=[page],
        blocks=[],
        tables=[],
        reading_order=[],
        engine_name="paddleocr_vl",
    )
    dto = to_document_parse_response(raw_response)
    assert len(dto.pages) == 1
    v = dto.pages[0].visual
    assert v.available is True
    assert v.kind == "processed_page"
    assert v.url == "/v1/doc/parse/req_vis_test/pages/0/image"


def test_doc_parse_api_returns_visual_metadata(api: Any) -> None:
    page = PageParseResult(
        page_index=0,
        geometry=PageGeometry(width=800.0, height=600.0, coordinate_space=CoordinateSpace.processed_image_pixels),
        blocks=[],
        visual=PageVisualDTO(available=True, kind="processed_page", url="/v1/doc/parse/req_vis_api/pages/0/image"),
    )
    fake_response = ParseResponse(
        request_id="req_vis_api",
        decision=ParseDecision(reason="Visual test"),
        pages=[page],
        blocks=[],
        tables=[],
        reading_order=[],
        engine_name="paddleocr_vl",
    )

    async def body(client):
        app.dependency_overrides[get_orchestrator] = lambda: DummyParser(fake_response)
        try:
            return await client.post(
                "/v1/doc/parse",
                files={"file": ("test.pdf", b"%PDF-1.4 dummy", "application/pdf")},
            )
        finally:
            app.dependency_overrides.pop(get_orchestrator, None)

    response = api(body)
    assert response.status_code == 200
    payload = response.json()
    assert payload["pages"][0]["visual"]["available"] is True
    assert payload["pages"][0]["visual"]["kind"] == "processed_page"
    assert payload["pages"][0]["visual"]["url"] == "/v1/doc/parse/req_vis_api/pages/0/image"


def test_get_parsed_page_image_returns_png(api: Any, tmp_path: Any) -> None:
    req_id = "req_test_get_img_123"
    custom_settings = Settings(parse_output_dir=str(tmp_path))
    dummy_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRdummy"
    save_page_visual_image(req_id, 0, dummy_png, custom_settings)

    app.dependency_overrides[get_settings] = lambda: custom_settings
    try:
        async def body(client):
            return await client.get(f"/v1/doc/parse/{req_id}/pages/0/image")

        response = api(body)
        assert response.status_code == 200
        assert "image/png" in response.headers["content-type"]
        assert response.content == dummy_png
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_get_parsed_page_image_correct_page_selection(api: Any, tmp_path: Any) -> None:
    req_id = "req_multipage_sel"
    custom_settings = Settings(parse_output_dir=str(tmp_path))
    png_p0 = b"PNG_PAGE_0_DATA"
    png_p1 = b"PNG_PAGE_1_DATA"
    save_page_visual_image(req_id, 0, png_p0, custom_settings)
    save_page_visual_image(req_id, 1, png_p1, custom_settings)

    app.dependency_overrides[get_settings] = lambda: custom_settings
    try:
        async def body(client):
            r0 = await client.get(f"/v1/doc/parse/{req_id}/pages/0/image")
            r1 = await client.get(f"/v1/doc/parse/{req_id}/pages/1/image")
            return r0, r1

        resp0, resp1 = api(body)
        assert resp0.status_code == 200
        assert resp0.content == png_p0
        assert resp1.status_code == 200
        assert resp1.content == png_p1
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_get_parsed_page_image_unknown_request_returns_404(api: Any) -> None:
    async def body(client):
        return await client.get("/v1/doc/parse/req_nonexistent_9999/pages/0/image")

    response = api(body)
    assert response.status_code == 404


def test_get_parsed_page_image_invalid_page_returns_404(api: Any, tmp_path: Any) -> None:
    req_id = "req_valid_exists"
    custom_settings = Settings(parse_output_dir=str(tmp_path))
    save_page_visual_image(req_id, 0, b"PNG_DATA", custom_settings)

    app.dependency_overrides[get_settings] = lambda: custom_settings
    try:
        async def body(client):
            return await client.get(f"/v1/doc/parse/{req_id}/pages/42/image")

        response = api(body)
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_get_parsed_page_image_path_traversal_impossible(api: Any, tmp_path: Any) -> None:
    # 1. Invalid request_id formats are rejected by regex before touching disk
    assert get_page_visual_image_path("../../etc/passwd", 0) is None
    assert get_page_visual_image_path("req_valid/../../etc", 0) is None
    assert get_page_visual_image_path("req_..", 0) is None
    assert get_page_visual_image_path("req_valid", -1) is None

    # 2. HTTP call with path traversal pattern
    async def body(client):
        return await client.get("/v1/doc/parse/..%2F..%2Fetc/pages/0/image")

    response = api(body)
    assert response.status_code in (404, 422)


def test_word_excel_visual_unavailable_does_not_fabricate_image() -> None:
    page_word = PageParseResult(
        page_index=0,
        geometry=PageGeometry(),
        blocks=[],
        visual=PageVisualDTO(available=False, kind=None, url=None),
        source_engine="word_text",
    )
    resp = ParseResponse(
        request_id="req_word_test",
        decision=ParseDecision(reason="Word parsed"),
        pages=[page_word],
        blocks=[],
        tables=[],
        reading_order=[],
        engine_name="word_text",
    )
    dto = to_document_parse_response(resp)
    assert dto.pages[0].visual.available is False
    assert dto.pages[0].visual.kind is None
    assert dto.pages[0].visual.url is None


def test_visual_artifact_retention_and_cleanup(tmp_path: Any) -> None:
    custom_settings = Settings(
        parse_output_dir=str(tmp_path),
        parse_output_retention_days=1,
    )
    # Create two visual artifact dirs
    save_page_visual_image("req_old_1", 0, b"OLD_IMG", custom_settings)
    save_page_visual_image("req_new_2", 0, b"NEW_IMG", custom_settings)

    old_dir = get_page_visual_dir("req_old_1", custom_settings)
    new_dir = get_page_visual_dir("req_new_2", custom_settings)

    import os
    import time
    # Backdate old_dir mtime to 2 days ago
    two_days_ago = time.time() - 2 * 86400
    os.utime(str(old_dir), (two_days_ago, two_days_ago))

    sweeper = ArtifactRetentionSweeper(custom_settings)
    result = sweeper.sweep()

    assert result.removed >= 1
    assert not old_dir.exists()
    assert new_dir.exists()


def test_concurrent_visual_saves_do_not_collide(tmp_path: Any) -> None:
    custom_settings = Settings(parse_output_dir=str(tmp_path))
    req_a = "req_concurrent_aaa"
    req_b = "req_concurrent_bbb"

    img_a = b"IMAGE_A_BYTES"
    img_b = b"IMAGE_B_BYTES"

    path_a = save_page_visual_image(req_a, 0, img_a, custom_settings)
    path_b = save_page_visual_image(req_b, 0, img_b, custom_settings)

    assert path_a != path_b
    assert path_a.read_bytes() == img_a
    assert path_b.read_bytes() == img_b
    assert get_page_visual_image_path(req_a, 0, custom_settings) == path_a
    assert get_page_visual_image_path(req_b, 0, custom_settings) == path_b

