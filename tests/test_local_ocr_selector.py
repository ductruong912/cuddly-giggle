"""Hardware decides the local OCR engine: GPU runs the VLM, CPU runs PP-OCRv6."""
from __future__ import annotations

import subprocess

import pytest

from config.config import settings
from services import local_ocr_selector
from services.local_ocr_selector import LocalOCRSelector, has_usable_gpu, log_gpu_availability


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
