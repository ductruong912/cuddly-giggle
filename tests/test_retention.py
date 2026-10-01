"""Saved artifacts must not grow until the disk is full.

One directory is written per document. Without a sweep this only ever grows, and
a full disk turns every subsequent write into a 500 that looks like a code bug.
"""
from __future__ import annotations

import dataclasses
import os
from pathlib import Path
import time

import pytest

from config.config import Settings, settings
from services.retention import SECONDS_PER_DAY, ArtifactRetentionSweeper


@pytest.fixture
def outputs(tmp_path: Path) -> Path:
    directory = tmp_path / "outputs"
    directory.mkdir()
    return directory


def configured(outputs: Path, *, retention_days: int) -> Settings:
    return dataclasses.replace(
        settings,
        parse_output_dir=str(outputs),
        parse_output_retention_days=retention_days,
    )


def artifact_dir(outputs: Path, name: str, *, age_days: float) -> Path:
    """Create a saved-artifact directory with a backdated modification time."""
    directory = outputs / name
    directory.mkdir()
    (directory / f"{name}.json").write_text("{}", encoding="utf-8")
    stamp = time.time() - age_days * SECONDS_PER_DAY
    os.utime(directory, (stamp, stamp))
    return directory


def test_only_the_expired_ones_go(outputs: Path) -> None:
    keep = artifact_dir(outputs, "keep", age_days=2)
    drop = artifact_dir(outputs, "drop", age_days=40)
    edge = artifact_dir(outputs, "edge", age_days=13.9)

    result = ArtifactRetentionSweeper(configured(outputs, retention_days=14)).sweep()

    assert keep.exists()
    assert not drop.exists()
    assert edge.exists()
    assert (result.removed, result.scanned) == (1, 3)


def test_retention_can_be_disabled(outputs: Path) -> None:
    ancient = artifact_dir(outputs, "ancient", age_days=9999)
    sweeper = ArtifactRetentionSweeper(configured(outputs, retention_days=0))

    result = sweeper.sweep()

    assert sweeper.enabled is False
    assert ancient.exists()
    assert result.removed == 0


def test_a_missing_output_directory_is_not_an_error(tmp_path: Path) -> None:
    """The sweep runs on a timer and must never raise into the event loop."""
    sweeper = ArtifactRetentionSweeper(configured(tmp_path / "absent", retention_days=7))

    assert sweeper.sweep().removed == 0


def test_loose_files_are_left_alone(outputs: Path) -> None:
    """Only per-document directories are managed; anything else is not ours."""
    stray = outputs / "notes.txt"
    stray.write_text("x", encoding="utf-8")
    stamp = time.time() - 9999 * SECONDS_PER_DAY
    os.utime(stray, (stamp, stamp))

    result = ArtifactRetentionSweeper(configured(outputs, retention_days=1)).sweep()

    assert stray.exists()
    assert result.scanned == 0


def test_an_undeletable_directory_is_counted_not_raised(
    outputs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One locked directory must not stop the rest of the sweep."""
    artifact_dir(outputs, "locked", age_days=99)
    artifact_dir(outputs, "deletable", age_days=99)

    real_rmtree = __import__("shutil").rmtree

    def selective_rmtree(path, *args, **kwargs):
        if Path(path).name == "locked":
            raise OSError("in use by another process")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr("services.retention.shutil.rmtree", selective_rmtree)

    result = ArtifactRetentionSweeper(configured(outputs, retention_days=1)).sweep()

    assert (result.removed, result.failed) == (1, 1)
    assert (outputs / "locked").exists()
