"""Setup must prepare the API's hardware profile without downloading in tests."""
from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys

import pytest

from config.config import settings
from scripts import preflight_runtime, setup_models, setup_runtime
from services import local_ocr_selector


def test_dependency_setup_imports_without_installed_runtime_packages() -> None:
    """A fresh venv must be able to reach pip before third-party packages exist."""
    code = """
import sys
from scripts import setup_runtime
from services.local_ocr_selector import has_usable_gpu
assert 'pydantic' not in sys.modules
assert 'dotenv' not in sys.modules
assert 'config.config' not in sys.modules
assert callable(setup_runtime.install_dependencies)
assert callable(has_usable_gpu)
"""
    subprocess.run([sys.executable, "-S", "-c", code], cwd=setup_runtime.REPO_ROOT, check=True)


@pytest.mark.parametrize("gpu,profile", [(False, "fast-onnx"), (True, "paddleocr-vl")])
def test_auto_setup_warms_only_the_selected_profile(monkeypatch, gpu, profile) -> None:
    events = []

    class FakeEngine:
        def __init__(self, label):
            self.label = label

        def warmup(self):
            assert os.environ["CUDDLY_GIGGLE_MODEL_SETUP"] == "1"
            events.append(self.label)

    monkeypatch.setattr(setup_models, "has_usable_gpu", lambda: gpu)
    monkeypatch.setattr(setup_models, "PaddleOCRFastEngine", lambda _: FakeEngine("fast-onnx"))
    monkeypatch.setattr(setup_models, "PaddleOCRVLEngine", lambda _: FakeEngine("paddleocr-vl"))
    monkeypatch.setattr(setup_models, "write_model_profile", lambda _, name: events.append(name))
    monkeypatch.setenv("CUDDLY_GIGGLE_MODEL_SETUP", "previous")

    assert setup_models.main(["--auto"]) == 0
    assert events == [profile, profile]
    assert os.environ["CUDDLY_GIGGLE_MODEL_SETUP"] == "previous"


def test_failed_model_setup_restores_environment(monkeypatch) -> None:
    monkeypatch.delenv("CUDDLY_GIGGLE_MODEL_SETUP", raising=False)

    def fail(_):
        raise RuntimeError("warmup failed")

    monkeypatch.setattr(setup_models, "_warm", fail)
    with pytest.raises(RuntimeError, match="warmup failed"):
        setup_models.main(["--fast-onnx"])
    assert "CUDDLY_GIGGLE_MODEL_SETUP" not in os.environ


@pytest.mark.parametrize("gpu", [False, True])
def test_dependency_install_selects_the_hardware_profile(monkeypatch, gpu) -> None:
    calls = []
    monkeypatch.setattr(local_ocr_selector, "has_usable_gpu", lambda: gpu)
    monkeypatch.setattr(setup_runtime.subprocess, "run", lambda command, **_: calls.append(command))
    setup_runtime.install_dependencies()
    assert len(calls) == 2
    expected = "paddlepaddle-gpu==3.3.0" if gpu else "paddlepaddle==3.3.0"
    assert calls[0][1:5] == ["-m", "pip", "install", expected]
    index = "cu126" if gpu else "cpu"
    assert calls[0][-2:] == ["-i", f"https://www.paddlepaddle.org.cn/packages/stable/{index}/"]
    assert calls[1][1:5] == ["-m", "pip", "install", "-r"]
    assert Path(calls[1][-1]).name == "requirements.txt"


@pytest.mark.parametrize("gpu", [False, True])
def test_all_setup_skips_llama_on_cpu(monkeypatch, gpu) -> None:
    monkeypatch.setattr(setup_runtime.platform, "system", lambda: "Windows")
    monkeypatch.setattr(local_ocr_selector, "has_usable_gpu", lambda: gpu)
    steps = setup_runtime.selected_steps(setup_runtime.parse_args(["--all"]))
    assert steps == (["dependencies", "ocr-models", "llama"] if gpu else ["dependencies", "ocr-models"])


def test_runtime_model_setup_delegates_to_auto(monkeypatch, tmp_path) -> None:
    from config import config

    model_root = tmp_path / "official_models"
    model_root.mkdir()
    (model_root / "model.bin").write_bytes(b"synthetic")
    monkeypatch.setattr(config, "settings", replace(settings, paddlex_cache_home=str(tmp_path)))
    calls = []
    monkeypatch.setattr(setup_models, "main", lambda args: calls.append(args))
    setup_runtime.warmup_ocr_models()
    assert calls == [["--auto"]]


@pytest.mark.parametrize("gpu,autostart,ok", [(False, True, True), (True, False, True), (True, True, False)])
def test_preflight_requires_local_llama_only_for_gpu_autostart(monkeypatch, tmp_path, gpu, autostart, ok) -> None:
    from services import llama

    model_root = tmp_path / "official_models"
    model_root.mkdir()
    (model_root / "model.bin").write_bytes(b"synthetic")
    monkeypatch.setenv("PADDLE_PDX_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(preflight_runtime, "app_settings", replace(
        settings, paddleocr_vl_use_gguf=True, llama_server_autostart=autostart,
    ))
    monkeypatch.setattr(preflight_runtime, "_find_spec", lambda _: True)
    monkeypatch.setattr(preflight_runtime, "_safe_import_paddle", lambda: {"installed": True})
    monkeypatch.setattr(preflight_runtime, "_nvidia_smi", lambda: "test GPU" if gpu else "unavailable")
    monkeypatch.setattr(local_ocr_selector, "has_usable_gpu", lambda: gpu)
    monkeypatch.setattr(llama, "is_llama_cpp_ready", lambda _: False)
    monkeypatch.setattr(llama, "is_artifact_ready", lambda *args: False)
    payload = preflight_runtime.build_preflight_payload()
    assert payload["ok"] is ok
    assert payload["llama_runtime"]["required"] is (gpu and autostart)
