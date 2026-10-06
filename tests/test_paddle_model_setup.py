"""CLI fallback must obey the same explicit model setup guard as Python OCR."""
from __future__ import annotations

from dataclasses import replace
from unittest.mock import Mock

import pytest

from config.config import settings
from core.engines.paddle import PaddleOCRVLEngine
from services.model_assets import ModelAssetsMissing, write_model_profile


def test_missing_profile_fails_before_python_or_cli(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("CUDDLY_GIGGLE_MODEL_SETUP", raising=False)
    app_settings = replace(settings, paddlex_cache_home=str(tmp_path))
    engine = PaddleOCRVLEngine(app_settings)
    python_api, cli = Mock(), Mock()
    monkeypatch.setattr(engine, "_try_python_api", python_api)
    monkeypatch.setattr(engine, "_try_cli", cli)

    with pytest.raises(ModelAssetsMissing, match="setup_models.py --gpu"):
        engine._parse_single("synthetic.png", "auto")

    python_api.assert_not_called()
    cli.assert_not_called()


def test_prepared_profile_still_allows_cli_fallback(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("CUDDLY_GIGGLE_MODEL_SETUP", raising=False)
    app_settings = replace(settings, paddlex_cache_home=str(tmp_path))
    (tmp_path / "synthetic-model.bin").touch()
    write_model_profile(app_settings, "gpu")
    engine = PaddleOCRVLEngine(app_settings)
    monkeypatch.setattr(engine, "_try_python_api", Mock(return_value=(None, "import_error")))
    cli = Mock(return_value=({"pages": [], "markdown": "synthetic text"}, ""))
    monkeypatch.setattr(engine, "_try_cli", cli)

    result = engine._parse_single("synthetic.png", "auto")

    assert result.markdown == "synthetic text"
    cli.assert_called_once_with("synthetic.png", "auto")
