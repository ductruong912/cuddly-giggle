"""Single-purpose image operators for scan cleanup.

Every operator takes and returns a BGR ``uint8`` array, so they compose in any
order. Luminance-only work happens on the L channel of LAB and is merged back,
which keeps colour intact: the detection and recognition models are trained on
colour and greyscale photographs, and flattening to a binary image throws away
the antialiasing gradients they rely on.

This module imports OpenCV at import time. Import it through
``core.preprocess.chain``, which degrades to a no-op when cv2 is absent.
"""
from __future__ import annotations

from pathlib import Path

# pyrefly: ignore [missing-import]
import cv2
# pyrefly: ignore [missing-import]
import numpy as np


# A skew estimate is only trustworthy when it comes from several text lines
# agreeing; below this, the page is probably a diagram and the median is noise.
_MIN_SKEW_SAMPLES = 8
# Text lines are merged with a wide, short kernel so a row of words becomes one
# contour whose long axis is the baseline.
_LINE_MERGE_KERNEL = (25, 3)
_SKEW_ESTIMATE_WIDTH = 1200


def read_image(path: str | Path) -> "np.ndarray | None":
    """Decode an image, tolerating non-ASCII paths that ``cv2.imread`` cannot open."""
    try:
        buffer = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if buffer.size == 0:
        return None
    return cv2.imdecode(buffer, cv2.IMREAD_COLOR)


def write_image(path: str | Path, image: "np.ndarray") -> bool:
    """Encode to ``path`` by suffix, tolerating non-ASCII paths on Windows."""
    destination = Path(path)
    ok, buffer = cv2.imencode(destination.suffix or ".png", image)
    if not ok:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    buffer.tofile(str(destination))
    return True


def _luminance(image: "np.ndarray") -> "np.ndarray":
    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _map_luminance(image: "np.ndarray", transform) -> "np.ndarray":  # type: ignore[no-untyped-def]
    """Apply ``transform`` to the L channel only, leaving colour untouched."""
    if image.ndim == 2:
        return transform(image)
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lightness, a_channel, b_channel = cv2.split(lab)
    merged = cv2.merge((transform(lightness), a_channel, b_channel))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def crop_scanner_border(
    image: "np.ndarray",
    *,
    dark_threshold: int = 40,
    max_fraction: float = 0.15,
) -> "np.ndarray":
    """Trim the near-black margin a scanner lid leaves around the page.

    Layout detection will happily emit regions over those margins, and on the VL
    path every spurious region costs a full generation call. Trimming is capped
    at ``max_fraction`` per side so a dark photograph is never eaten alive.
    """
    gray = _luminance(image)
    height, width = gray.shape[:2]
    if height < 4 or width < 4:
        return image

    row_means = gray.mean(axis=1)
    col_means = gray.mean(axis=0)

    def _lead(values: "np.ndarray", limit: int) -> int:
        count = 0
        while count < limit and values[count] < dark_threshold:
            count += 1
        return count

    top = _lead(row_means, int(height * max_fraction))
    bottom = _lead(row_means[::-1], int(height * max_fraction))
    left = _lead(col_means, int(width * max_fraction))
    right = _lead(col_means[::-1], int(width * max_fraction))

    if not (top or bottom or left or right):
        return image
    return image[top : height - bottom, left : width - right]


def estimate_skew_degrees(
    image: "np.ndarray",
    *,
    max_degrees: float = 10.0,
) -> float | None:
    """Return the rotation, in degrees, that would put the text baselines level.

    ``None`` means "no correction": too few text lines to be confident, or an
    estimate beyond ``max_degrees``, which is more likely a bad read than a real
    skew — whole-page 90 degree rotation is a different problem, handled by
    PaddleOCR's orientation classifier rather than here.

    The angle is measured from the long axis of merged text lines, which is
    stable on documents where a Hough transform would lock onto table rules.
    """
    gray = _luminance(image)
    height, width = gray.shape[:2]
    if height < 32 or width < 32:
        return None

    # Estimate on a downscaled copy: the angle is a global property and the
    # sweep is the expensive part.
    if width > _SKEW_ESTIMATE_WIDTH:
        scale = _SKEW_ESTIMATE_WIDTH / width
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    # Otsu on the inverted image puts ink in the foreground.
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, _LINE_MERGE_KERNEL)
    merged = cv2.dilate(binary, kernel, iterations=1)

    contours, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    angles: list[float] = []
    for contour in contours:
        (_, _), (rect_width, rect_height), angle = cv2.minAreaRect(contour)
        long_side, short_side = max(rect_width, rect_height), min(rect_width, rect_height)
        # Keep contours shaped like a line of text; blobs and rules are not.
        if long_side < 40 or short_side < 3 or long_side < short_side * 4:
            continue
        # minAreaRect reports (0, 90]; fold it onto the nearest horizontal.
        if angle > 45:
            angle -= 90
        angles.append(angle)

    if len(angles) < _MIN_SKEW_SAMPLES:
        return None

    median = float(np.median(angles))
    if abs(median) > max_degrees:
        return None
    return median


def rotate(image: "np.ndarray", degrees: float) -> "np.ndarray":
    """Rotate by ``degrees``, growing the canvas so no content is clipped.

    Edges replicate rather than fill black: a black wedge in the corner is a
    high-contrast artefact that layout detection treats as content.
    """
    height, width = image.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, degrees, 1.0)

    cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
    bounded_width = int(height * sin + width * cos)
    bounded_height = int(height * cos + width * sin)
    matrix[0, 2] += bounded_width / 2.0 - center[0]
    matrix[1, 2] += bounded_height / 2.0 - center[1]

    return cv2.warpAffine(
        image,
        matrix,
        (bounded_width, bounded_height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def deskew(image: "np.ndarray", *, max_degrees: float, min_degrees: float) -> tuple["np.ndarray", float]:
    """Level the text baselines. Returns the image and the angle actually applied."""
    angle = estimate_skew_degrees(image, max_degrees=max_degrees)
    if angle is None or abs(angle) < min_degrees:
        return image, 0.0
    return rotate(image, angle), angle


def flatten_illumination(image: "np.ndarray", *, blur_kernel: int = 21) -> "np.ndarray":
    """Divide out an uneven background: phone shadows, book curl, lamp gradients.

    The background is estimated by dilating ink away and median-blurring what is
    left, then the page is divided by it. Unlike thresholding this keeps the
    grey ramp around each glyph.
    """

    def _flatten(channel: "np.ndarray") -> "np.ndarray":
        dilated = cv2.dilate(channel, np.ones((7, 7), np.uint8))
        background = cv2.medianBlur(dilated, blur_kernel)
        return cv2.divide(channel, background, scale=255)

    return _map_luminance(image, _flatten)


def denoise(image: "np.ndarray", *, kernel_size: int = 3) -> "np.ndarray":
    """Median filter for fax and photocopy speckle.

    Deliberately small: a wider kernel erodes thin strokes, and thin strokes are
    the digits on an invoice line.
    """
    return cv2.medianBlur(image, kernel_size)


def apply_clahe(
    image: "np.ndarray",
    *,
    clip_limit: float = 2.0,
    tile_grid: int = 8,
) -> "np.ndarray":
    """Local contrast equalisation, for carbon copies and washed-out thermal scans."""
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile_grid, tile_grid))
    return _map_luminance(image, clahe.apply)
