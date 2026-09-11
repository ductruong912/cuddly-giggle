"""Scan preprocessing: the operators, and the chain that sequences them.

The operators need OpenCV, which is a transitive dependency of paddleocr and so
is absent from the CI subset; those tests skip there. The chain's fallback
behaviour is tested without it, because that is exactly the environment the
fallback exists for.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from config.config import Settings, settings as base_settings
from core.preprocess.chain import preprocess_file


cv2 = pytest.importorskip("cv2", reason="OpenCV ships with paddleocr, not with the CI subset")
np = pytest.importorskip("numpy")

from core.preprocess import image_ops  # noqa: E402


PAGE_WIDTH, PAGE_HEIGHT = 1000, 1400


def synthetic_page(width: int = PAGE_WIDTH, height: int = PAGE_HEIGHT) -> "np.ndarray":
    """A light page with dark bars standing in for lines of text."""
    page = np.full((height, width, 3), 245, np.uint8)
    for row in range(14):
        top = 120 + row * 85
        cv2.rectangle(page, (110, top), (width - 130, top + 26), (25, 25, 25), -1)
    return page


def enabled(**overrides: object) -> Settings:
    """The real settings with the chain switched on and nothing else changed."""
    return dataclasses.replace(base_settings, preprocess_enabled=True, **overrides)


# =====================================================================================
# Skew estimation and correction
# =====================================================================================

def test_an_upright_page_reports_no_skew() -> None:
    assert image_ops.estimate_skew_degrees(synthetic_page()) == pytest.approx(0.0, abs=0.1)


@pytest.mark.parametrize("applied", [-6.0, -3.0, -1.5, 1.5, 3.0, 6.0])
def test_the_estimate_is_the_angle_that_undoes_the_tilt(applied: float) -> None:
    """The returned angle is a correction, so feeding it to rotate levels the page."""
    tilted = image_ops.rotate(synthetic_page(), applied)

    estimate = image_ops.estimate_skew_degrees(tilted)

    assert estimate == pytest.approx(-applied, abs=0.2)
    residual = image_ops.estimate_skew_degrees(image_ops.rotate(tilted, estimate))
    assert residual == pytest.approx(0.0, abs=0.2)


def test_a_tilt_beyond_the_maximum_is_refused() -> None:
    """A large angle is likelier a bad read than a real skew, and 90 degrees is
    the orientation classifier's job, not this one's."""
    tilted = image_ops.rotate(synthetic_page(), 20.0)

    assert image_ops.estimate_skew_degrees(tilted, max_degrees=10.0) is None


def test_too_few_text_lines_yields_no_estimate() -> None:
    """A median over two contours is noise, not a measurement."""
    sparse = np.full((400, 400, 3), 245, np.uint8)
    cv2.rectangle(sparse, (40, 40), (360, 70), (25, 25, 25), -1)

    assert image_ops.estimate_skew_degrees(sparse) is None


def test_deskew_leaves_a_negligible_tilt_alone() -> None:
    """Rotating costs a resample; below the threshold there is nothing to buy."""
    page = image_ops.rotate(synthetic_page(), 0.05)

    corrected, angle = image_ops.deskew(page, max_degrees=10.0, min_degrees=0.2)

    assert angle == 0.0
    assert corrected is page


def test_deskew_reports_the_angle_it_applied() -> None:
    corrected, angle = image_ops.deskew(
        image_ops.rotate(synthetic_page(), 4.0), max_degrees=10.0, min_degrees=0.2
    )

    assert angle == pytest.approx(-4.0, abs=0.2)
    assert image_ops.estimate_skew_degrees(corrected) == pytest.approx(0.0, abs=0.2)


def test_rotation_grows_the_canvas_rather_than_clipping_content() -> None:
    rotated = image_ops.rotate(synthetic_page(), 10.0)

    assert rotated.shape[0] > PAGE_HEIGHT and rotated.shape[1] > PAGE_WIDTH


# =====================================================================================
# Border cropping
# =====================================================================================

def test_the_scanner_border_is_trimmed_off() -> None:
    bordered = cv2.copyMakeBorder(
        synthetic_page(), 60, 60, 40, 40, cv2.BORDER_CONSTANT, value=(0, 0, 0)
    )

    cropped = image_ops.crop_scanner_border(bordered)

    assert cropped.shape[0] == pytest.approx(PAGE_HEIGHT, abs=4)
    assert cropped.shape[1] == pytest.approx(PAGE_WIDTH, abs=4)


def test_a_page_without_a_border_is_returned_untouched() -> None:
    page = synthetic_page()

    assert image_ops.crop_scanner_border(page) is page


def test_cropping_never_eats_more_than_its_share_of_a_dark_page() -> None:
    """A dark photograph must survive: the cap is what stops the trim running away."""
    dark = np.full((600, 600, 3), 5, np.uint8)

    cropped = image_ops.crop_scanner_border(dark, max_fraction=0.15)

    assert cropped.shape[0] >= 600 * 0.7 and cropped.shape[1] >= 600 * 0.7


# =====================================================================================
# Photometric operators
# =====================================================================================

def test_illumination_flattening_evens_out_a_lighting_gradient() -> None:
    page = synthetic_page()
    gradient = np.linspace(0.35, 1.0, page.shape[1], dtype=np.float32)
    shadowed = np.clip(page * gradient[None, :, None], 0, 255).astype(np.uint8)

    flattened = image_ops.flatten_illumination(shadowed)

    def paper_brightness(image: "np.ndarray", column: slice) -> float:
        # Row 60 sits in the top margin, above the first bar: paper, not ink.
        return float(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)[60, column].mean())

    left, right = slice(0, 200), slice(-200, None)
    before = paper_brightness(shadowed, right) - paper_brightness(shadowed, left)
    after = paper_brightness(flattened, right) - paper_brightness(flattened, left)
    assert abs(after) < abs(before) / 4


@pytest.mark.parametrize(
    "operator",
    [
        image_ops.flatten_illumination,
        image_ops.denoise,
        image_ops.apply_clahe,
    ],
)
def test_the_photometric_operators_preserve_shape_and_dtype(operator) -> None:  # type: ignore[no-untyped-def]
    """They compose in any order, so none may change the array contract."""
    page = synthetic_page()

    result = operator(page)

    assert result.shape == page.shape and result.dtype == page.dtype


def test_denoising_removes_speckle_without_destroying_the_text() -> None:
    page = synthetic_page()
    speckled = page.copy()
    generator = np.random.default_rng(seed=17)
    mask = generator.random(page.shape[:2]) < 0.02
    speckled[mask] = 255

    cleaned = image_ops.denoise(speckled)

    assert np.abs(cleaned.astype(int) - page.astype(int)).mean() < np.abs(
        speckled.astype(int) - page.astype(int)
    ).mean()


# =====================================================================================
# Round-tripping through disk
# =====================================================================================

def test_images_round_trip_through_a_non_ascii_path(tmp_path: Path) -> None:
    """cv2.imread cannot open these on Windows; the encode/decode helpers must."""
    destination = tmp_path / "hoá-đơn.png"
    page = synthetic_page(200, 200)

    assert image_ops.write_image(destination, page)
    restored = image_ops.read_image(destination)

    assert restored is not None and restored.shape == page.shape


def test_reading_a_missing_file_returns_none(tmp_path: Path) -> None:
    assert image_ops.read_image(tmp_path / "absent.png") is None


# =====================================================================================
# The chain
# =====================================================================================

def test_the_chain_is_inert_until_it_is_switched_on(tmp_path: Path) -> None:
    source = tmp_path / "page.png"
    image_ops.write_image(source, synthetic_page(200, 200))

    result = preprocess_file(str(source), app_settings=base_settings)

    assert result.path == str(source)
    assert not result.changed and not result.steps


def test_enabling_the_chain_without_a_step_still_does_nothing(tmp_path: Path) -> None:
    """PREPROCESS_ENABLED on its own is not an instruction to do anything."""
    source = tmp_path / "page.png"
    image_ops.write_image(source, synthetic_page(200, 200))

    result = preprocess_file(str(source), app_settings=enabled())

    assert not result.changed


def test_the_chain_writes_a_corrected_page_and_times_each_step(tmp_path: Path) -> None:
    source = tmp_path / "page.png"
    destination = tmp_path / "clean.png"
    image_ops.write_image(source, image_ops.rotate(synthetic_page(), 4.0))

    result = preprocess_file(
        str(source),
        output_path=str(destination),
        app_settings=enabled(preprocess_deskew=True, preprocess_clahe=True),
    )

    assert result.changed and result.path == str(destination)
    assert destination.is_file()
    assert [step.name for step in result.steps] == ["deskew", "clahe", "write"]
    assert result.total_seconds > 0
    written = image_ops.read_image(destination)
    assert image_ops.estimate_skew_degrees(written) == pytest.approx(0.0, abs=0.3)


def test_the_deskew_step_records_the_angle_it_applied(tmp_path: Path) -> None:
    """The log line is how a preprocessing regression gets attributed later."""
    source = tmp_path / "page.png"
    image_ops.write_image(source, image_ops.rotate(synthetic_page(), 3.0))

    result = preprocess_file(
        str(source),
        output_path=str(tmp_path / "clean.png"),
        app_settings=enabled(preprocess_deskew=True),
    )

    deskew_step = next(step for step in result.steps if step.name == "deskew")
    assert "-3.0" in deskew_step.detail
    assert "deskew=" in result.summary()


def test_a_freshly_rendered_page_skips_the_exif_decode(tmp_path: Path) -> None:
    """A page this process just rasterized has no EXIF, and the EXIF-aware
    decode is the slower path — running it there is pure overhead."""
    source = tmp_path / "page.png"
    image_ops.write_image(source, synthetic_page(200, 200))
    options = enabled(preprocess_exif_transpose=True, preprocess_clahe=True)

    from_disk = preprocess_file(str(source), output_path=str(tmp_path / "a.png"), app_settings=options)
    rendered = preprocess_file(
        str(source), output_path=str(tmp_path / "b.png"), app_settings=options, allow_exif=False
    )

    assert "exif" in [step.name for step in from_disk.steps]
    assert "exif" not in [step.name for step in rendered.steps]
    assert rendered.changed


def test_an_undecodable_page_falls_back_to_the_original(tmp_path: Path) -> None:
    """A parse must survive a corrupt page: a dirty scan still OCRs."""
    source = tmp_path / "broken.png"
    source.write_bytes(b"this is not a PNG")

    result = preprocess_file(
        str(source),
        output_path=str(tmp_path / "clean.png"),
        app_settings=enabled(preprocess_deskew=True),
    )

    assert result.path == str(source) and not result.changed


def test_a_raising_operator_falls_back_to_the_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "page.png"
    image_ops.write_image(source, synthetic_page(200, 200))

    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("operator failed")

    monkeypatch.setattr(image_ops, "apply_clahe", explode)

    result = preprocess_file(
        str(source),
        output_path=str(tmp_path / "clean.png"),
        app_settings=enabled(preprocess_clahe=True),
    )

    assert result.path == str(source) and not result.changed


def test_the_finished_page_is_saved_for_inspection_when_asked(tmp_path: Path) -> None:
    source = tmp_path / "page.png"
    image_ops.write_image(source, synthetic_page(200, 200))

    result = preprocess_file(
        str(source),
        output_path=str(tmp_path / "clean.png"),
        app_settings=enabled(
            preprocess_clahe=True,
            preprocess_save_images=True,
            preprocess_debug_dir=str(tmp_path / "debug"),
        ),
        debug_name="doc/page_0001",
    )

    assert result.debug_path is not None
    assert (tmp_path / "debug" / "doc" / "page_0001.png").is_file()


def test_no_inspection_copy_is_saved_without_a_name(tmp_path: Path) -> None:
    source = tmp_path / "page.png"
    image_ops.write_image(source, synthetic_page(200, 200))

    result = preprocess_file(
        str(source),
        output_path=str(tmp_path / "clean.png"),
        app_settings=enabled(
            preprocess_clahe=True,
            preprocess_save_images=True,
            preprocess_debug_dir=str(tmp_path / "debug"),
        ),
    )

    assert result.debug_path is None


# =====================================================================================
# Naming saved diagnostics
# =====================================================================================

def test_saved_pages_are_named_after_the_upload_not_its_staged_uuid() -> None:
    """Uploads are staged under a UUID, which would make the saved images useless."""
    from config.pipeline_logging import source_document_context
    from core.engines.paddle import PaddleOCRVLEngine

    staged = r"C:\tmp\9f2c4ab1e0f4471aa6d3b2c1d0e5f678.pdf"

    with source_document_context("HSPL_Q1_8.pdf"):
        assert PaddleOCRVLEngine._document_stem(staged) == "HSPL_Q1_8"
    assert PaddleOCRVLEngine._document_stem(staged) == "9f2c4ab1e0f4471aa6d3b2c1d0e5f678"


def test_a_hostile_upload_name_cannot_escape_the_debug_directory() -> None:
    """The stem becomes a directory name, and an upload can be called anything."""
    from config.pipeline_logging import source_document_context
    from core.engines.paddle import PaddleOCRVLEngine

    with source_document_context("../../etc/passwd.pdf"):
        stem = PaddleOCRVLEngine._document_stem("staged.pdf")

    assert "/" not in stem and "\\" not in stem and ".." not in stem


# =====================================================================================
# Configuration guards
# =====================================================================================

@pytest.mark.parametrize(
    "overrides",
    [
        {"preprocess_denoise_kernel": 4},
        {"preprocess_denoise_kernel": 1},
        {"preprocess_clahe_clip_limit": 0.0},
        {"preprocess_deskew_max_degrees": 0.0},
        {"preprocess_deskew_min_degrees": -1.0},
        {"preprocess_deskew_min_degrees": 20.0, "preprocess_deskew_max_degrees": 10.0},
    ],
)
def test_bad_tuning_fails_at_startup_not_mid_parse(overrides: dict) -> None:
    """cv2 would reject an even kernel at call time, i.e. inside a request."""
    with pytest.raises(ValueError):
        dataclasses.replace(base_settings, **overrides)
