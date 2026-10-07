"""Hardware selection, Paddle configuration, PDF text and recognition geometry."""
from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from config.config import settings
from core.domain.schemas import Block, BlockType, PageParseResult
from core.engines.base import EngineParseResult, image_page_geometry
from core.engines.native import (
    PdfTextEngine,
    is_pdf_text_result_usable,
    repair_legacy_vietnamese_text,
)
from core.engines.paddle import PaddleOCRVLEngine
from core.engines.paddle_fast import PaddleOCRFastEngine
from services import local_ocr_selector
from services.local_ocr_selector import LocalOCRSelector, has_usable_gpu, log_gpu_availability
from services.model_assets import ModelAssetsMissing, write_model_profile


class StubEngine:
    """Marks which factory the selector chose."""

    def __init__(self, app_settings: object, label: str) -> None:
        self.settings = app_settings
        self.label = label


def selector(*, gpu: bool) -> LocalOCRSelector:
    return LocalOCRSelector(
        settings,
        gpu_available=lambda: gpu,
        vlm_factory=lambda s: StubEngine(s, "vlm"),
        cpu_factory=lambda s: StubEngine(s, "fast"),
    )


def test_a_gpu_machine_runs_the_vlm() -> None:
    assert selector(gpu=True).select().label == "vlm"


def test_a_cpu_machine_runs_the_fast_tier() -> None:
    assert selector(gpu=False).select().label == "fast"


def test_the_startup_line_names_the_chosen_engine() -> None:
    assert log_gpu_availability(gpu_available=lambda: True) is True
    assert log_gpu_availability(gpu_available=lambda: False) is False


def test_a_cuda_build_without_a_gpu_is_not_a_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    """paddlepaddle-gpu is always "compiled with CUDA", GPU present or not.

    Checking the build instead of the device count selects the VLM on a CPU-only
    machine, which is precisely the fallback that must work.
    """
    has_usable_gpu.cache_clear()

    class FakeCuda:
        @staticmethod
        def device_count() -> int:
            return 0

    class FakeDevice:
        cuda = FakeCuda()

        @staticmethod
        def is_compiled_with_cuda() -> bool:
            return True  # true for the wheel, irrelevant to the hardware

    fake_paddle = type("FakePaddle", (), {"device": FakeDevice()})()
    monkeypatch.setitem(__import__("sys").modules, "paddle", fake_paddle)
    monkeypatch.setitem(__import__("sys").modules, "torch", None)
    monkeypatch.setattr(
        local_ocr_selector.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
    )

    try:
        assert has_usable_gpu() is False
    finally:
        has_usable_gpu.cache_clear()


def test_a_real_device_count_is_a_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    has_usable_gpu.cache_clear()

    class FakeCuda:
        @staticmethod
        def device_count() -> int:
            return 1

    fake_paddle = type(
        "FakePaddle", (), {"device": type("D", (), {"cuda": FakeCuda()})()}
    )()
    monkeypatch.setitem(__import__("sys").modules, "paddle", fake_paddle)
    monkeypatch.setitem(__import__("sys").modules, "torch", None)

    try:
        assert has_usable_gpu() is True
    finally:
        has_usable_gpu.cache_clear()


def test_no_gpu_anywhere_falls_back_to_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    """No torch, no paddle CUDA device, no nvidia-smi: the fast tier must be chosen."""
    has_usable_gpu.cache_clear()
    monkeypatch.setitem(__import__("sys").modules, "torch", None)
    monkeypatch.setitem(__import__("sys").modules, "paddle", None)
    monkeypatch.setattr(
        local_ocr_selector.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("nvidia-smi")),
    )

    try:
        assert has_usable_gpu() is False
    finally:
        has_usable_gpu.cache_clear()


def test_the_configured_models_are_the_ones_asked_for() -> None:
    """GPU path is PaddleOCR-VL 1.6; CPU path is PP-OCRv6 detection + recognition."""
    assert settings.paddleocr_vl_pipeline_version == "v1.6"
    assert "PP-OCRv6" in settings.fast_ocr_detection_model_name
    assert "PP-OCRv6" in settings.fast_ocr_recognition_model_name


def test_missing_profile_fails_before_python_or_cli(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("CUDDLY_GIGGLE_MODEL_SETUP", raising=False)
    app_settings = replace(settings, paddlex_cache_home=str(tmp_path))
    engine = PaddleOCRVLEngine(app_settings)
    python_api, cli = Mock(), Mock()
    monkeypatch.setattr(engine, "_try_python_api", python_api)
    monkeypatch.setattr(engine, "_try_cli", cli)

    with pytest.raises(ModelAssetsMissing, match="setup_models.py --gpu"):
        engine._parse_single("synthetic.png", "auto")

    python_api.assert_not_called()
    cli.assert_not_called()


def test_prepared_profile_still_allows_cli_fallback(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("CUDDLY_GIGGLE_MODEL_SETUP", raising=False)
    app_settings = replace(settings, paddlex_cache_home=str(tmp_path))
    (tmp_path / "synthetic-model.bin").touch()
    write_model_profile(app_settings, "gpu")
    engine = PaddleOCRVLEngine(app_settings)
    monkeypatch.setattr(engine, "_try_python_api", Mock(return_value=(None, "import_error")))
    cli = Mock(return_value=({"pages": [], "markdown": "synthetic text"}, ""))
    monkeypatch.setattr(engine, "_try_cli", cli)

    result = engine._parse_single("synthetic.png", "auto")

    assert result.markdown == "synthetic text"
    cli.assert_called_once_with("synthetic.png", "auto")


@pytest.mark.parametrize("unwarp", [False, True])
def test_vl_uses_external_orientation_normalization_and_keeps_unwarping_independent(unwarp):
    engine = PaddleOCRVLEngine(replace(
        settings, paddleocr_vl_use_gguf=False,
        paddleocr_vl_auto_rotate=True, paddleocr_vl_use_doc_unwarping=unwarp,
    ))

    kwargs = engine._extra_kwargs()
    args = engine._extra_cli_args()

    assert kwargs["use_doc_orientation_classify"] is False
    assert kwargs["use_doc_unwarping"] is unwarp
    assert args[args.index("--use_doc_orientation_classify") + 1] == "False"
    assert args[args.index("--use_doc_unwarping") + 1] == str(unwarp)


def test_raw_pdf_keeps_paddle_orientation_fallback_enabled():
    engine = PaddleOCRVLEngine(replace(settings, paddleocr_vl_auto_rotate=True))

    args = engine._extra_cli_args("unrasterized.pdf")

    assert args[args.index("--use_doc_orientation_classify") + 1] == "True"


@pytest.mark.parametrize("input_path,expected", [("normalized.png", False), ("unrasterized.pdf", True)])
def test_python_api_uses_internal_orientation_only_for_raw_pdf(
    monkeypatch, input_path, expected
):
    engine = PaddleOCRVLEngine(replace(
        settings, paddleocr_vl_auto_rotate=True, paddleocr_vl_use_gguf=False
    ))
    pipeline = Mock()
    pipeline.predict.return_value = []
    monkeypatch.setattr(engine, "_load_pipeline_cls", lambda: object)
    monkeypatch.setattr(engine, "_build_kwargs", lambda *_: {})
    monkeypatch.setattr(engine, "_get_or_create_pipeline", lambda *_: pipeline)

    result, error = engine._try_python_api(input_path, "auto")

    assert result == []
    assert not error
    assert pipeline.predict.call_args.kwargs["use_doc_orientation_classify"] is expected


def test_vl_auto_rotation_preprocesses_images_even_when_cleanup_is_disabled(
    monkeypatch, tmp_path
):
    np = pytest.importorskip("numpy")
    image_module = pytest.importorskip("PIL.Image")
    from core.engines.paddle import PaddleOCRVLEngine
    from core.preprocess import image_ops

    source = tmp_path / "sideways.png"
    original = np.zeros((80, 120, 3), dtype=np.uint8)
    original[5:20, 10:110] = 255
    image_module.fromarray(original).save(source)
    monkeypatch.setenv("CUDDLY_GIGGLE_MODEL_SETUP", "1")

    def rotate(image):
        return np.rot90(image, 1).copy(), 90

    monkeypatch.setattr("core.preprocess.orientation.normalize_document_orientation", rotate)
    engine = PaddleOCRVLEngine(replace(
        settings, paddleocr_vl_auto_rotate=True, preprocess_enabled=False
    ))
    page_images, cleanup = engine._prepare_page_images(str(source))
    try:
        assert page_images is not None and len(page_images) == 1
        assert page_images[0] != str(source)
        assert np.array_equal(image_ops.read_image(page_images[0]), np.rot90(image_ops.read_image(source), 1))
    finally:
        cleanup()


@pytest.mark.parametrize("value,expected", [(None, False), ("false", False), ("true", True)])
def test_unwarping_environment_default_and_override(value, expected):
    env = dict(os.environ, DATABASE_URL="")
    env.pop("PADDLEOCR_VL_USE_DOC_UNWARPING", None)
    if value is not None:
        env["PADDLEOCR_VL_USE_DOC_UNWARPING"] = value
    # Settings defaults are evaluated on import; isolate from the user's .env.
    result = subprocess.run(
        [sys.executable, "-c", "from unittest.mock import patch; "
         "patch('dotenv.load_dotenv').start(); "
         "from config.config import Settings; "
         "print(Settings().paddleocr_vl_use_doc_unwarping)"],
        env=env, capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == str(expected)


@pytest.mark.parametrize("rotate", [False, True])
@pytest.mark.parametrize("unwarp", [False, True])
def test_original_geometry_fallback_requires_no_rotation_or_unwarping(monkeypatch, rotate, unwarp):
    monkeypatch.setenv("CUDDLY_GIGGLE_MODEL_SETUP", "1")
    engine = PaddleOCRVLEngine(replace(
        settings, paddleocr_vl_auto_rotate=rotate,
        paddleocr_vl_use_doc_unwarping=unwarp, preprocess_enabled=False,
    ))
    page = SimpleNamespace(geometry=None)
    geometry = object()
    geometry_reader = Mock(return_value=geometry)
    monkeypatch.setattr(engine, "_try_python_api", Mock(return_value=({}, "")))
    monkeypatch.setattr("core.engines.paddle.normalize_engine_output",
                        Mock(return_value=([page], "synthetic", {})))
    monkeypatch.setattr("core.engines.paddle.image_page_geometry", geometry_reader)
    monkeypatch.setattr("core.engines.paddle.preview_capture_enabled", lambda: False)

    result = engine._parse_single("synthetic.png", "auto")

    if rotate or unwarp:
        assert result.pages[0].geometry is None
        geometry_reader.assert_not_called()
    else:
        assert result.pages[0].geometry is geometry
        geometry_reader.assert_called_once_with("synthetic.png", matches_original=True)


try:
    import fitz
except ImportError:
    fitz = None


SECOND_PAGE_NOTE = (
    "Trang hai: ghi chu giao hang tai kho Ha Noi, lien he bo phan mua hang "
    "truoc khi giao de xac nhan so luong va thoi gian nhan hang."
)


def build_pdf(path: Path, *, second_page_text: str) -> Path:
    """A two-page PDF with a real text layer and a crude three-column table."""
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 100), "HOA DON MUA HANG", fontsize=16)
    page.insert_text((72, 130), "So PO: 215497-000 OI ngay 05 thang 06 nam 2026", fontsize=11)
    rows = [
        ("Ma hang", "So luong", "Don gia"),
        ("TT-0012", "4", "125000"),
        ("TT-0099", "11", "98000"),
        ("TT-1234", "2", "1450000"),
    ]
    y = 170
    for code, quantity, price in rows:
        page.insert_text((72, y), code, fontsize=10)
        page.insert_text((220, y), quantity, fontsize=10)
        page.insert_text((360, y), price, fontsize=10)
        y += 22
    second = document.new_page()
    second.insert_text((72, 100), second_page_text, fontsize=11)
    document.save(str(path))
    document.close()
    return path


@pytest.fixture
def text_pdf(tmp_path: Path) -> Path:
    return build_pdf(tmp_path / "purchase_order.pdf", second_page_text=SECOND_PAGE_NOTE)


def result_with(text: str, pages: int = 1) -> EngineParseResult:
    """Wrap raw text as an engine result, for the usability heuristics."""
    return EngineParseResult(
        engine_name="test",
        pages=[
            PageParseResult(
                page_index=index,
                blocks=[
                    Block(
                        block_id=f"b{index}",
                        type=BlockType.text,
                        content=text,
                        page_index=index,
                    )
                ],
            )
            for index in range(pages)
        ],
        raw={},
    )


# -- encoding repair ---------------------------------------------------------







# -- usability heuristics ----------------------------------------------------

READABLE_PAGE = (
    "Hoa don mua hang so 215497 ngay 05 thang 06 nam 2026, giao tai kho Ha Noi. "
    "Ma hang TT-0012 so luong 4 don gia 125000. Ma hang TT-0099 so luong 11 "
    "don gia 98000. Tong cong thanh tien da bao gom thue gia tri gia tang."
)














# -- the engine end to end ---------------------------------------------------


@pytest.mark.skipif(fitz is None, reason="PyMuPDF is required to build PDF fixtures")
class TestPdfTextEngine:
    def test_legacy_text_is_converted(self, ) -> None:
        """TCVN3 uses codepoints correct Vietnamese never does; those identify it."""
        legacy = "Ngµy giao hµng"

        assert repair_legacy_vietnamese_text(legacy) != legacy


    def test_correct_unicode_is_left_alone(self, ) -> None:
        """The regression this guards: 'Nguyên Văn' was being rewritten to 'Nguyờn Văn'.

        Letters like 'ê' sit on both sides of the TCVN3 table, so treating them as
        markers corrupts text that was already correct.
        """
        for text in ("Nguyên Văn", "Tiếng Việt", "Địa chỉ"):
            assert repair_legacy_vietnamese_text(text) == text


    @pytest.mark.parametrize("text", ["", "plain ascii", "PO 215497", "123.456"])
    def test_text_without_markers_is_untouched(self, text: str) -> None:
        assert repair_legacy_vietnamese_text(text) == text


    def test_a_readable_text_layer_is_usable(self, ) -> None:
        assert is_pdf_text_result_usable(result_with(READABLE_PAGE)) is True


    def test_every_page_must_carry_text(self, ) -> None:
        """The ratio is 1.0: one near-empty page sends the whole document to OCR.

        A cover sheet or a scanned annex mixed into a digital PDF is exactly the
        case this catches, and reading half a document is worse than reading none.
        """
        result = result_with(READABLE_PAGE, pages=2)
        result.pages[1].blocks[0].content = "Trang 2"

        assert is_pdf_text_result_usable(result) is False


    def test_an_empty_result_is_not_usable(self, ) -> None:
        assert is_pdf_text_result_usable(EngineParseResult(engine_name="test", pages=[])) is False


    def test_a_sparse_text_layer_is_not_usable(self, ) -> None:
        """Too few characters means a scan with stray marks, not a text layer."""
        assert is_pdf_text_result_usable(result_with("PO 1")) is False


    def test_a_garbled_text_layer_falls_back_to_ocr(self, ) -> None:
        """Private-use codepoints mean an undecodable embedded font."""
        garbled = "".join(chr(0xE000 + index % 100) for index in range(400))

        assert is_pdf_text_result_usable(result_with(garbled)) is False


    def test_a_broken_font_cmap_falls_back_to_ocr(self, ) -> None:
        """Digits substituted mid-word ('Nguy6n') decode as valid but wrong letters."""
        corrupt = " ".join(["Nguy6n", "Tr4n", "Ph5m", "H0ang", "L3", "V0", "D1nh", "B9i"] * 8)

        assert is_pdf_text_result_usable(result_with(corrupt)) is False


    def test_the_engine_reads_a_real_text_layer(self, text_pdf: Path) -> None:
        result = PdfTextEngine(settings).parse(str(text_pdf))

        assert len(result.pages) == 2
        combined = "\n".join(
            block.content for page in result.pages for block in page.blocks
        )
        assert "HOA DON MUA HANG" in combined
        assert "TT-0012" in combined
        assert "Trang hai" in combined
        first_page_text = "\n".join(block.content for block in result.pages[0].blocks)
        for code in ("TT-0012", "TT-0099", "TT-1234"):
            assert code in first_page_text
        assert is_pdf_text_result_usable(result) is True
        assert result.pages[0].geometry is not None
        assert result.pages[0].geometry.coordinate_space == "original"


    @pytest.mark.parametrize("rotation", [0, 90, 180, 270])
    def test_pdf_bbox_matches_rotated_preview(self, tmp_path: Path, rotation: int) -> None:
        path = tmp_path / "rotated.pdf"
        with fitz.open() as document:
            page = document.new_page(width=300, height=400)
            page.insert_text((40, 80), "Synthetic bbox")
            original = page.get_text("blocks")[0][:4]
            page.set_rotation(rotation)
            expected = fitz.Rect(original) * page.rotation_matrix
            document.save(path)
        result = PdfTextEngine(settings).parse(str(path)).pages[0]
        assert result.geometry is not None
        assert (result.geometry.width, result.geometry.height) == ((400, 300) if rotation % 180 else (300, 400))
        polygon = result.blocks[0].bbox
        assert min(point.x for point in polygon) == pytest.approx(expected.x0)
        assert max(point.x for point in polygon) == pytest.approx(expected.x1)
        assert min(point.y for point in polygon) == pytest.approx(expected.y0)
        assert max(point.y for point in polygon) == pytest.approx(expected.y1)


    def test_a_document_with_one_sparse_page_falls_back_to_ocr(self, tmp_path: Path) -> None:
        """End to end: the strict all-pages rule applies to a real file, not just a stub."""
        sparse = build_pdf(tmp_path / "sparse.pdf", second_page_text="Trang 2")

        assert is_pdf_text_result_usable(PdfTextEngine(settings).parse(str(sparse))) is False


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
    engine = PaddleOCRFastEngine(replace(settings, fast_ocr_auto_rotate=auto_rotate,
                                         ocr_external_rotation=False, pdf_rasterize_enabled=False))
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


@pytest.mark.parametrize("engine_cls,flag", [
    (PaddleOCRFastEngine, "fast_ocr_auto_rotate"),
    (PaddleOCRVLEngine, "paddleocr_vl_auto_rotate"),
])
@pytest.mark.parametrize("external", [False, True])
def test_rotation_mode_enables_exactly_one_classifier(engine_cls, flag, external):
    engine = engine_cls(replace(settings, ocr_external_rotation=external, **{flag: True}))
    kwargs = (engine._build_pipeline_kwargs() if engine_cls is PaddleOCRFastEngine
              else engine._extra_kwargs())
    assert engine._external_auto_rotate() is external
    assert kwargs["use_doc_orientation_classify"] is (not external)


@pytest.mark.parametrize("engine_cls,flag", [
    (PaddleOCRFastEngine, "fast_ocr_auto_rotate"),
    (PaddleOCRVLEngine, "paddleocr_vl_auto_rotate"),
])
def test_external_rotation_requires_pdf_page_images(engine_cls, flag):
    engine = engine_cls(replace(settings, ocr_external_rotation=True,
                                pdf_rasterize_enabled=False, **{flag: True}))
    with pytest.raises(RuntimeError, match="External PDF rotation requires"):
        engine.parse("synthetic.pdf")


@pytest.mark.skipif(fitz is None, reason="PyMuPDF is required to build PDF fixtures")
def test_fast_pdf_rotates_then_deskews_each_page_and_cleans_up(monkeypatch, tmp_path):
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    from core.preprocess import image_ops
    source = build_pdf(tmp_path / "synthetic.pdf", second_page_text=SECOND_PAGE_NOTE)
    before = source.read_bytes()
    events = []
    staged = []
    monkeypatch.setenv("CUDDLY_GIGGLE_MODEL_SETUP", "1")

    def rotate(image):
        events.append("rotate")
        return np.rot90(image).copy(), 90

    def deskew(image, **kwargs):
        events.append("deskew")
        assert image.shape[1] > image.shape[0]
        return image, 0

    monkeypatch.setattr("core.preprocess.orientation.normalize_document_orientation", rotate)
    monkeypatch.setattr(image_ops, "deskew", deskew)
    engine = PaddleOCRFastEngine(replace(
        settings, ocr_external_rotation=True, fast_ocr_auto_rotate=True,
        pdf_rasterize_enabled=True, pdf_rasterize_dpi=72,
        preprocess_enabled=True, preprocess_deskew=True,
        preprocess_exif_transpose=False, preprocess_border_crop=False,
        preprocess_illumination=False, preprocess_denoise=False, preprocess_clahe=False,
    ))

    class Pipeline:
        def predict(self, path):
            events.append("ocr")
            staged.append(Path(path))
            assert Path(path).exists() and Path(path).suffix == ".png"
            return [{"rec_texts": ["Synthetic"], "rec_scores": [0.95],
                     "rec_boxes": [[10, 20, 100, 40]]}]

    monkeypatch.setattr(engine, "_get_or_create_pipeline", lambda: Pipeline())
    result = engine.parse(str(source))
    assert events == ["rotate", "deskew", "rotate", "deskew", "ocr", "ocr"]
    assert [page.page_index for page in result.pages] == [0, 1]
    assert result.pages[1].blocks[0].page_index == 1
    assert len(result.raw["paddleocr"]) == 2
    assert source.read_bytes() == before
    assert all(not path.exists() for path in staged)


def test_fast_pdf_cleans_pages_when_ocr_fails(monkeypatch, tmp_path):
    engine = PaddleOCRFastEngine(replace(settings, ocr_external_rotation=True))
    staged = tmp_path / "staged"
    staged.mkdir()
    page = staged / "page.png"
    page.touch()
    import shutil
    monkeypatch.setattr(engine, "_prepare_page_images",
                        lambda _: ([str(page)], lambda: shutil.rmtree(staged)))
    monkeypatch.setattr(engine, "_parse_single", Mock(side_effect=RuntimeError("synthetic failure")))
    with pytest.raises(RuntimeError, match="synthetic failure"):
        engine.parse("synthetic.pdf")
    assert not staged.exists()
