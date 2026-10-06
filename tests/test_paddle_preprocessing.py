"""VL orientation and unwarping must remain independently configurable."""
from dataclasses import replace
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from config.config import settings
from core.engines.paddle import PaddleOCRVLEngine


@pytest.mark.parametrize("rotate", [False, True])
@pytest.mark.parametrize("unwarp", [False, True])
def test_python_and_cli_keep_preprocessing_flags_independent(rotate, unwarp):
    engine = PaddleOCRVLEngine(replace(
        settings, paddleocr_vl_use_gguf=False,
        paddleocr_vl_auto_rotate=rotate, paddleocr_vl_use_doc_unwarping=unwarp,
    ))

    kwargs = engine._extra_kwargs()
    args = engine._extra_cli_args()

    assert kwargs["use_doc_orientation_classify"] is rotate
    assert kwargs["use_doc_unwarping"] is unwarp
    assert args[args.index("--use_doc_orientation_classify") + 1] == str(rotate)
    assert args[args.index("--use_doc_unwarping") + 1] == str(unwarp)


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
