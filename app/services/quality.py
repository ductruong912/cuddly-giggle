from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.domain.schemas import QualityFlags


@dataclass
class QualityAssessment:
    flags: QualityFlags
    score: float


def assess_document_quality(input_path: str) -> QualityAssessment:
    path = Path(input_path)
    if path.suffix.lower() == ".pdf":
        # PDF quality is better assessed per rendered page by OCR engines.
        # Keep neutral defaults and defer to model confidence.
        return QualityAssessment(flags=QualityFlags(), score=0.9)

    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        return QualityAssessment(flags=QualityFlags(), score=0.6)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape

    blur_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    is_blur = blur_var < 110.0

    mean_intensity = float(np.mean(gray))
    std_intensity = float(np.std(gray))
    is_illumination_issue = mean_intensity < 55.0 or mean_intensity > 220.0 or std_intensity < 24.0

    # Skew estimation by dominant line orientation in Hough transform.
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, 180)
    skew_deg = 0.0
    if lines is not None and len(lines) > 0:
        thetas = []
        for line in lines[: min(len(lines), 80)]:
            rho, theta = line[0]
            deg = (theta * 180 / np.pi) - 90
            while deg > 45:
                deg -= 90
            while deg < -45:
                deg += 90
            thetas.append(float(deg))
        if thetas:
            skew_deg = float(np.median(thetas))
    is_skew = abs(skew_deg) >= 3.0

    is_low_resolution = min(height, width) < 1200

    # Screen photo heuristic: visible perspective distortion + dark border tendency.
    border_px = int(min(height, width) * 0.03)
    border_px = max(border_px, 2)
    center_crop = gray[border_px:-border_px, border_px:-border_px]
    border_mask = gray.copy()
    if center_crop.size > 0:
        border_mask[border_px:-border_px, border_px:-border_px] = 0
    border_mean = float(np.mean(border_mask[border_mask > 0])) if np.any(border_mask > 0) else 0.0
    center_mean = float(np.mean(center_crop)) if center_crop.size > 0 else border_mean
    is_screen_photo = abs(border_mean - center_mean) > 30 and is_skew

    flags = QualityFlags(
        skew=is_skew,
        blur=is_blur,
        illumination_issue=is_illumination_issue,
        screen_photo=is_screen_photo,
        low_resolution=is_low_resolution,
    )

    penalties = (
        (0.14 if flags.skew else 0.0)
        + (0.20 if flags.blur else 0.0)
        + (0.14 if flags.illumination_issue else 0.0)
        + (0.18 if flags.screen_photo else 0.0)
        + (0.10 if flags.low_resolution else 0.0)
    )
    score = max(0.0, min(1.0, 1.0 - penalties))
    return QualityAssessment(flags=flags, score=score)
