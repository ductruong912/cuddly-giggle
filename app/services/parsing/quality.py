from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.core.config import Settings, settings
from app.domain.schemas import QualityFlags


@dataclass
class QualityAssessment:
    flags: QualityFlags
    score: float


def assess_document_quality(input_path: str, app_settings: Settings = settings) -> QualityAssessment:
    path = Path(input_path)
    if path.suffix.lower() in {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".xlsm"}:
        # Text documents are better assessed by their parser or rendered pages.
        # Keep neutral defaults and defer to model confidence.
        return QualityAssessment(flags=QualityFlags(), score=app_settings.quality_pdf_default_score)

    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        return QualityAssessment(flags=QualityFlags(), score=app_settings.quality_unreadable_image_score)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape

    blur_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    is_blur = blur_var < app_settings.quality_blur_var_threshold

    mean_intensity = float(np.mean(gray))
    std_intensity = float(np.std(gray))
    is_illumination_issue = (
        mean_intensity < app_settings.quality_dark_mean_threshold
        or mean_intensity > app_settings.quality_bright_mean_threshold
        or std_intensity < app_settings.quality_low_contrast_std_threshold
    )

    # Skew estimation by dominant line orientation in Hough transform.
    edges = cv2.Canny(gray, app_settings.quality_canny_threshold1, app_settings.quality_canny_threshold2, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, app_settings.quality_hough_threshold)
    skew_deg = 0.0
    if lines is not None and len(lines) > 0:
        thetas = []
        for line in lines[: min(len(lines), app_settings.quality_skew_max_lines)]:
            rho, theta = line[0]
            deg = (theta * 180 / np.pi) - 90
            while deg > 45:
                deg -= 90
            while deg < -45:
                deg += 90
            thetas.append(float(deg))
        if thetas:
            skew_deg = float(np.median(thetas))
    is_skew = abs(skew_deg) >= app_settings.quality_skew_deg_threshold

    is_low_resolution = min(height, width) < app_settings.quality_min_resolution_px

    # Screen photo heuristic: visible perspective distortion + dark border tendency.
    border_px = int(min(height, width) * app_settings.quality_screen_photo_border_fraction)
    border_px = max(border_px, 2)
    center_crop = gray[border_px:-border_px, border_px:-border_px]
    border_mask = gray.copy()
    if center_crop.size > 0:
        border_mask[border_px:-border_px, border_px:-border_px] = 0
    border_mean = float(np.mean(border_mask[border_mask > 0])) if np.any(border_mask > 0) else 0.0
    center_mean = float(np.mean(center_crop)) if center_crop.size > 0 else border_mean
    is_screen_photo = abs(border_mean - center_mean) > app_settings.quality_screen_photo_border_diff and is_skew

    flags = QualityFlags(
        skew=is_skew,
        blur=is_blur,
        illumination_issue=is_illumination_issue,
        screen_photo=is_screen_photo,
        low_resolution=is_low_resolution,
    )

    penalties = (
        (app_settings.quality_penalty_skew if flags.skew else 0.0)
        + (app_settings.quality_penalty_blur if flags.blur else 0.0)
        + (app_settings.quality_penalty_illumination if flags.illumination_issue else 0.0)
        + (app_settings.quality_penalty_screen_photo if flags.screen_photo else 0.0)
        + (app_settings.quality_penalty_low_resolution if flags.low_resolution else 0.0)
    )
    score = max(0.0, min(1.0, 1.0 - penalties))
    return QualityAssessment(flags=flags, score=score)
