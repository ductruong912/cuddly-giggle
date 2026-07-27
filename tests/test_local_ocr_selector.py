from __future__ import annotations

import logging

from config.config import Settings
from services.local_ocr_selector import LocalOCRSelector, log_gpu_availability


def test_select_uses_vlm_when_gpu_is_available() -> None:
    vlm = object()
    cpu = object()
    selector = LocalOCRSelector(
        Settings(),
        gpu_available=lambda: True,
        vlm_factory=lambda _: vlm,
        cpu_factory=lambda _: cpu,
    )

    assert selector.select() is vlm


def test_select_uses_paddle_v6_when_gpu_is_unavailable() -> None:
    vlm = object()
    cpu = object()
    selector = LocalOCRSelector(
        Settings(),
        gpu_available=lambda: False,
        vlm_factory=lambda _: vlm,
        cpu_factory=lambda _: cpu,
    )

    assert selector.select() is cpu


def test_log_gpu_availability_reports_gpu(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="services.local_ocr_selector"):
        log_gpu_availability(gpu_available=lambda: True)

    assert "local OCR hardware: GPU detected; engine=PaddleOCR-VL" in caplog.messages
