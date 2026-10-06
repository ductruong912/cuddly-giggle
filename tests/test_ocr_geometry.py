"""BBox extents must describe the recognition image, never an estimated text extent."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from config.config import settings
from core.engines.base import image_page_geometry
from core.engines.paddle_fast import PaddleOCRFastEngine


@pytest.mark.parametrize("angle", [0, 90, 180, 270])
def test_preview_inverse_rotation_matches_paddle_image_rotation(angle):
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    from core.domain.schemas import PageParseResult
    from core.engines.preview import attach_page_previews, capture_preview_context

    width, height = 240, 160
    source = np.zeros((height, width, 3), dtype=np.uint8)
    output_width, output_height = (height, width) if angle in (90, 270) else (width, height)
    mat = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1)
    mat[0, 2] += (output_width - width) / 2
    mat[1, 2] += (output_height - height) / 2
    image = cv2.warpAffine(source, mat, (output_width, output_height))
    page = PageParseResult(page_index=0)
    live = [{"doc_preprocessor_res": {"input_img": source, "output_img": image, "angle": angle,
             "model_settings": {"use_doc_unwarping": False, "use_doc_orientation_classify": True}}}]
    with capture_preview_context(100_000, 200):
        attach_page_previews([page], live, input_matches_original=True)
    mapping = page.geometry.original
    inverse = np.array(mapping.transform).reshape(2, 3)
    for original in [(0, 0), (30, 50), (width, height)]:
        rotated = mat @ np.array([*original, 1])
        assert inverse @ np.array([*rotated, 1]) == pytest.approx(original)
    assert page.geometry.coordinate_space == ("original" if angle == 0 else "processed")


def test_unwarped_preview_is_opt_in_bounded_and_does_not_mutate_bbox():
    np = pytest.importorskip("numpy")
    pytest.importorskip("PIL.Image")
    from core.domain.schemas import Block, PageParseResult, Point
    from core.engines.preview import attach_page_previews, capture_preview_context, preview_capture_enabled

    block = Block(block_id="synthetic", type="title", bbox=[Point(x=10, y=20)])
    page = PageParseResult(page_index=0, blocks=[block])
    image = np.zeros((160, 240, 3), dtype=np.uint8)
    image[:, :, 2] = 255  # BGR red; confirm preview encoding isn't blue.
    live = [{"doc_preprocessor_res": {"input_img": image, "output_img": image, "angle": 0,
             "model_settings": {"use_doc_unwarping": True}}}]
    attach_page_previews([page], live, input_matches_original=True)
    assert page.geometry is None and page.preview_image is None
    with capture_preview_context(1, 200):
        attach_page_previews([page], live, input_matches_original=True)
    assert page.preview_image is None
    assert page.geometry.original is None
    with capture_preview_context(100_000, 120):
        attach_page_previews([page], live, input_matches_original=True)
    assert page.preview_image.startswith("data:image/jpeg;base64,")
    assert not preview_capture_enabled()
    import base64
    from io import BytesIO
    from PIL import Image
    preview = Image.open(BytesIO(base64.b64decode(page.preview_image.split(",", 1)[1])))
    assert preview.size == (120, 80)
    assert preview.getpixel((0, 0))[0] > 250
    assert page.geometry.width == 240
    assert page.geometry.original is None
    assert block.bbox == [Point(x=10, y=20)]


def test_preprocessed_input_does_not_claim_original_mapping():
    np = pytest.importorskip("numpy")
    from core.domain.schemas import PageParseResult
    from core.engines.preview import attach_page_previews, capture_preview_context

    image = np.zeros((160, 240, 3), dtype=np.uint8)
    live = [{"doc_preprocessor_res": {"input_img": image, "output_img": image, "angle": 0,
             "model_settings": {"use_doc_unwarping": False}}}]
    page = PageParseResult(page_index=0)
    with capture_preview_context(100_000, 120):
        attach_page_previews([page], live, input_matches_original=False)
    assert page.geometry.coordinate_space == "processed"
    assert page.geometry.original is None


def test_vl_adapter_retains_live_processed_image_only_for_ui(monkeypatch, tmp_path):
    np = pytest.importorskip("numpy")
    image_module = pytest.importorskip("PIL.Image")
    from core.engines.paddle import PaddleOCRVLEngine
    from core.engines.preview import capture_preview_context

    path = tmp_path / "synthetic.png"
    image_module.new("RGB", (240, 160)).save(path)
    image = np.zeros((160, 240, 3), dtype=np.uint8)
    live = [{"page_index": 0, "markdown": "Synthetic", "parsing_res_list": [
        {"block_label": "doc_title", "block_content": "Synthetic", "block_bbox": [10, 20, 100, 50]}],
        "doc_preprocessor_res": {"input_img": image, "output_img": image, "angle": 0,
                                 "model_settings": {"use_doc_unwarping": True}}}]
    monkeypatch.setenv("CUDDLY_GIGGLE_MODEL_SETUP", "1")
    engine = PaddleOCRVLEngine(replace(settings, paddleocr_vl_auto_rotate=True, preprocess_enabled=False))
    monkeypatch.setattr(engine, "_try_python_api", lambda *_: (live, ""))
    old_result = engine._parse_single(str(path), "auto")
    assert old_result.pages[0].geometry is None
    assert old_result.pages[0].preview_image is None
    with capture_preview_context(100_000, 120):
        result = engine._parse_single(str(path), "auto")
    assert result.markdown == old_result.markdown
    assert result.pages[0].geometry.coordinate_space == "processed"
    assert result.pages[0].preview_image.startswith("data:image/jpeg;base64,")
    assert result.pages[0].blocks[0].bbox == old_result.pages[0].blocks[0].bbox
    merged = engine._merge_page_results([result, result])
    assert merged.pages[1].page_index == 1
    assert merged.pages[1].blocks[0].page_index == 1
    assert merged.pages[1].preview_image == result.pages[0].preview_image


def test_no_internal_preprocessing_retains_original_geometry():
    np = pytest.importorskip("numpy")
    from core.domain.schemas import PageParseResult
    from core.engines.preview import attach_page_previews, capture_preview_context

    image = np.zeros((160, 240, 3), dtype=np.uint8)
    live = [{"model_settings": {"use_doc_preprocessor": False},
             "doc_preprocessor_res": {"output_img": image}}]
    page = PageParseResult(page_index=0)
    with capture_preview_context(100_000, 120):
        attach_page_previews([page], live, input_matches_original=True)
    assert page.geometry.coordinate_space == "original"
    assert page.preview_image is None


def test_capture_context_resets_after_failure():
    from core.engines.preview import capture_preview_context, preview_capture_enabled

    with pytest.raises(RuntimeError):
        with capture_preview_context(100, 10):
            assert preview_capture_enabled()
            raise RuntimeError("synthetic failure")
    assert not preview_capture_enabled()


@pytest.mark.parametrize("auto_rotate", [False, True])
def test_fast_pdf_uses_actual_recognition_image_dimensions(monkeypatch, auto_rotate):
    engine = PaddleOCRFastEngine(replace(settings, fast_ocr_auto_rotate=auto_rotate))
    output = [
        {"page_index": index, "rec_texts": [f"Synthetic page {index}"], "rec_scores": [0.95],
         "rec_polys": [[[10, 20], [100, 22], [99, 50], [9, 48]]],
         "doc_preprocessor_res": {"output_img": SimpleNamespace(shape=(1200, 800, 3))}}
        for index in range(2)
    ]
    pipeline = Mock()
    pipeline.predict_iter.return_value = iter(output)
    monkeypatch.setattr(engine, "_get_or_create_pipeline", lambda: pipeline)
    monkeypatch.setattr(engine, "_preprocessed_input", lambda path: (path, None))
    monkeypatch.setattr(engine, "_get_input_page_count", lambda _: 2)
    result = engine.parse("synthetic.pdf")
    assert len(result.pages) == 2
    for index, page in enumerate(result.pages):
        assert page.page_index == index
        assert page.geometry.width == 800
        assert page.geometry.height == 1200
        assert page.geometry.coordinate_space == ("processed" if auto_rotate else "original")
        assert [(point.x, point.y) for point in page.blocks[0].bbox] == [(10, 20), (100, 22), (99, 50), (9, 48)]


def test_image_geometry_distinguishes_original_processed_and_unknown(tmp_path):
    image_module = pytest.importorskip("PIL.Image")
    path = tmp_path / "synthetic.png"
    image_module.new("RGB", (200, 300)).save(path)
    original = image_page_geometry(str(path), matches_original=True)
    assert (original.width, original.height, original.coordinate_space) == (200, 300, "original")
    assert image_page_geometry(str(path), matches_original=False).coordinate_space == "processed"
    assert image_page_geometry(str(tmp_path / "missing.png"), matches_original=True) is None


def test_exif_orientation_is_not_overlaid_on_browser_original(tmp_path):
    image_module = pytest.importorskip("PIL.Image")
    image = image_module.new("RGB", (200, 300))
    exif = image.getexif()
    exif[274] = 6
    path = tmp_path / "synthetic.jpg"
    image.save(path, exif=exif)
    assert image_page_geometry(str(path), matches_original=True) is None
