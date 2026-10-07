"""Run the configured preprocessing steps over one page image.

Each step is independently switchable so its effect on accuracy and on latency
can be measured on its own; the chain as a whole is off unless
``PREPROCESS_ENABLED`` is set. Nothing here is allowed to fail a parse: a
missing OpenCV, an unreadable image, or a raising operator all fall back to the
original file and log, because a slightly dirty scan still OCRs and a crashed
request does not.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import time

from config.config import Settings, settings


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StepTiming:
    """How long one step took, and whether it changed anything."""

    name: str
    seconds: float
    detail: str = ""


@dataclass
class PreprocessResult:
    """What the chain did to one page."""

    # The image OCR should read: the rewritten file, or the original when the
    # chain was off, unavailable, or unable to improve on it.
    path: str
    changed: bool = False
    steps: list[StepTiming] = field(default_factory=list)
    debug_path: str | None = None

    @property
    def total_seconds(self) -> float:
        return sum(step.seconds for step in self.steps)

    def summary(self) -> str:
        """One-line, log-friendly account of the work, in order."""
        if not self.steps:
            return "none"
        return " ".join(
            f"{step.name}={step.seconds * 1000:.0f}ms"
            + (f"({step.detail})" if step.detail else "")
            for step in self.steps
        )


def _any_step_enabled(app_settings: Settings) -> bool:
    return any(
        (
            app_settings.preprocess_exif_transpose,
            app_settings.preprocess_border_crop,
            app_settings.preprocess_deskew,
            app_settings.preprocess_illumination,
            app_settings.preprocess_denoise,
            app_settings.preprocess_clahe,
        )
    )


def preprocess_file(
    input_path: str,
    *,
    output_path: str | None = None,
    app_settings: Settings = settings,
    debug_name: str | None = None,
    allow_exif: bool = True,
    auto_rotate: bool = False,
) -> PreprocessResult:
    """Clean up one page image, writing the result to ``output_path``.

    Args:
        input_path: the page image to read.
        output_path: where to write the cleaned image. Defaults to overwriting
            ``input_path``, which is what the rasterized-page flow wants since
            those are throwaway temp files.
        debug_name: stem for the saved copy when ``PREPROCESS_SAVE_IMAGES`` is
            on. No copy is saved without it.
        allow_exif: set False for images this process just rendered. They carry
            no EXIF, and the EXIF-aware decode is the slower of the two paths,
            so honouring the setting there would cost time for no effect.

    Returns:
        A result whose ``path`` is always safe to hand to the OCR engine.
    """
    unchanged = PreprocessResult(path=input_path)
    cleanup_enabled = app_settings.preprocess_enabled and _any_step_enabled(app_settings)
    if not cleanup_enabled and not auto_rotate:
        return unchanged

    try:
        from core.preprocess import image_ops
    except ImportError:
        # OpenCV is a transitive dependency of paddleocr; a text-only install
        # will not have it, and that must not be fatal.
        if auto_rotate:
            raise RuntimeError("Automatic document orientation requires OpenCV and PaddleOCR.")
        logger.warning("preprocessing is enabled but OpenCV is unavailable; skipping")
        return unchanged

    try:
        return _run_chain(
            image_ops,
            input_path,
            output_path or input_path,
            app_settings,
            debug_name,
            allow_exif,
            auto_rotate,
        )
    except Exception:
        if auto_rotate:
            raise
        logger.warning("preprocessing failed for %s; using the original image", input_path, exc_info=True)
        return unchanged


def _run_chain(
    image_ops,  # type: ignore[no-untyped-def]
    input_path: str,
    output_path: str,
    app_settings: Settings,
    debug_name: str | None,
    allow_exif: bool,
    auto_rotate: bool,
) -> PreprocessResult:
    steps: list[StepTiming] = []
    cleanup_enabled = app_settings.preprocess_enabled and _any_step_enabled(app_settings)
    use_exif = cleanup_enabled and app_settings.preprocess_exif_transpose and allow_exif

    started = time.perf_counter()
    image = _load(image_ops, input_path, use_exif)
    if image is None:
        if auto_rotate:
            raise RuntimeError(f"Could not decode {input_path} for automatic orientation normalization.")
        logger.warning("could not decode %s for preprocessing; using the original", input_path)
        return PreprocessResult(path=input_path)
    if use_exif:
        steps.append(StepTiming("exif", time.perf_counter() - started))

    orientation_changed = False
    if auto_rotate:
        from core.preprocess.orientation import normalize_document_orientation

        started = time.perf_counter()
        image, angle = normalize_document_orientation(image)
        orientation_changed = angle != 0
        steps.append(StepTiming("orientation", time.perf_counter() - started, f"{angle}deg"))

    # Order is deliberate. The border goes first: a black margin corrupts both
    # the skew estimate and the background statistics. Deskew comes next so the
    # remaining filters see level text. Contrast work goes last, on an image
    # that is already geometrically correct.
    if cleanup_enabled and app_settings.preprocess_border_crop:
        started = time.perf_counter()
        before = image.shape[:2]
        image = image_ops.crop_scanner_border(image)
        after = image.shape[:2]
        detail = "" if before == after else f"{before[1]}x{before[0]}->{after[1]}x{after[0]}"
        steps.append(StepTiming("border_crop", time.perf_counter() - started, detail))

    if cleanup_enabled and app_settings.preprocess_deskew:
        started = time.perf_counter()
        image, angle = image_ops.deskew(
            image,
            max_degrees=app_settings.preprocess_deskew_max_degrees,
            min_degrees=app_settings.preprocess_deskew_min_degrees,
        )
        detail = f"{angle:+.2f}deg" if angle else "none"
        steps.append(StepTiming("deskew", time.perf_counter() - started, detail))

    if cleanup_enabled and app_settings.preprocess_illumination:
        started = time.perf_counter()
        image = image_ops.flatten_illumination(image)
        steps.append(StepTiming("illumination", time.perf_counter() - started))

    if cleanup_enabled and app_settings.preprocess_denoise:
        started = time.perf_counter()
        image = image_ops.denoise(image, kernel_size=app_settings.preprocess_denoise_kernel)
        steps.append(StepTiming("denoise", time.perf_counter() - started))

    if cleanup_enabled and app_settings.preprocess_clahe:
        started = time.perf_counter()
        image = image_ops.apply_clahe(image, clip_limit=app_settings.preprocess_clahe_clip_limit)
        steps.append(StepTiming("clahe", time.perf_counter() - started))

    if not cleanup_enabled and not orientation_changed:
        return PreprocessResult(path=input_path, steps=steps)

    started = time.perf_counter()
    if not image_ops.write_image(output_path, image):
        if auto_rotate and orientation_changed:
            raise RuntimeError(f"Could not save the normalized page image to {output_path}.")
        logger.warning("could not encode the preprocessed image for %s; using the original", input_path)
        return PreprocessResult(path=input_path)
    steps.append(StepTiming("write", time.perf_counter() - started))

    debug_path = _save_debug_copy(image_ops, image, app_settings, debug_name)
    return PreprocessResult(path=output_path, changed=True, steps=steps, debug_path=debug_path)


def _load(image_ops, input_path: str, use_exif: bool):  # type: ignore[no-untyped-def]
    """Decode the page, honouring EXIF orientation when that step is enabled.

    OpenCV discards EXIF, so a phone photo of a document decodes sideways and no
    later step can recover it — the orientation classifier is a separate,
    model-based control and is off by default.
    """
    if not use_exif:
        return image_ops.read_image(input_path)

    try:
        # pyrefly: ignore [missing-import]
        import numpy as np
        # pyrefly: ignore [missing-import]
        from PIL import Image, ImageOps

        with Image.open(input_path) as opened:
            upright = ImageOps.exif_transpose(opened).convert("RGB")
            return np.asarray(upright)[:, :, ::-1].copy()  # RGB -> BGR
    except Exception:
        logger.warning("EXIF-aware decode failed for %s; falling back to OpenCV", input_path, exc_info=True)
        return image_ops.read_image(input_path)


def _save_debug_copy(
    image_ops,  # type: ignore[no-untyped-def]
    image,  # type: ignore[no-untyped-def]
    app_settings: Settings,
    debug_name: str | None,
) -> str | None:
    """Write the fully preprocessed page so the chain can be inspected by eye."""
    if not app_settings.preprocess_save_images or not debug_name:
        return None
    destination = Path(app_settings.preprocess_debug_dir) / f"{debug_name}.png"
    try:
        if image_ops.write_image(destination, image):
            return str(destination.resolve())
    except OSError:
        logger.warning("could not save the preprocessed image to %s", destination, exc_info=True)
    return None
