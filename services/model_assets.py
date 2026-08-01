"""Record and validate model files prepared by the explicit setup scripts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol


class SettingsLike(Protocol):
    paddlex_cache_home: str


class ModelAssetsMissing(RuntimeError):
    pass


_MANIFEST_NAME = "cuddly-giggle-models.json"

# Profiles already proven complete this process. The check reads the manifest and
# stats every recorded model file, which is far too much I/O to repeat per request;
# `set` membership and `add` are atomic under the GIL, so no lock is needed.
_verified_profiles: set[tuple[str, str]] = set()


def _cache_path(app_settings: SettingsLike) -> Path:
    return Path(app_settings.paddlex_cache_home)


def _manifest_path(app_settings: SettingsLike) -> Path:
    return _cache_path(app_settings) / _MANIFEST_NAME


def write_model_profile(app_settings: SettingsLike, profile: str) -> None:
    """Record every currently cached model file for an explicitly prepared profile."""
    cache_path = _cache_path(app_settings)
    files = [
        str(path.relative_to(cache_path))
        for path in cache_path.rglob("*")
        if path.is_file() and path.name != _MANIFEST_NAME
    ]
    manifest_path = _manifest_path(app_settings)
    manifest: dict[str, list[str]] = {}
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                manifest = {
                    str(name): [str(item) for item in items]
                    for name, items in loaded.items()
                    if isinstance(items, list)
                }
        except (OSError, json.JSONDecodeError):
            pass
    manifest[profile] = files
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def require_model_profile(app_settings: SettingsLike, profile: str) -> None:
    """Fail before PaddleX can initiate an implicit network download.

    The result is memoised per (cache directory, profile): a prepared profile does
    not become unprepared while the service is running, and re-verifying it on
    every parse would stat every cached model file again.
    """
    cache_key = (str(_cache_path(app_settings)), profile)
    if cache_key in _verified_profiles:
        return
    _verify_model_profile(app_settings, profile)
    _verified_profiles.add(cache_key)


def _verify_model_profile(app_settings: SettingsLike, profile: str) -> None:
    manifest_path = _manifest_path(app_settings)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = manifest[profile]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        raise ModelAssetsMissing(
            f"Model profile {profile!r} is not prepared. "
            f"Run scripts/setup_models.py --{profile}."
        ) from None

    cache_path = _cache_path(app_settings)
    missing = [item for item in files if not (cache_path / item).is_file()]
    if missing:
        raise ModelAssetsMissing(
            f"Model profile {profile!r} is incomplete ({missing[0]} is missing). "
            f"Run scripts/setup_models.py --{profile}."
        )
