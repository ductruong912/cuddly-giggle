from __future__ import annotations

from config.config import Settings
from services.local_ocr_selector import LocalOCRSelector


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
