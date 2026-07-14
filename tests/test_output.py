"""Tests for parse artifact persistence."""
from __future__ import annotations

from dataclasses import replace

from app.core.config import settings
from app.domain.schemas import ParseDecision, ParseResponse
from app.services import output


def _response(markdown: str | None) -> ParseResponse:
    return ParseResponse(
        request_id="req_test",
        decision=ParseDecision(reason="stubbed"),
        pages=[],
        blocks=[],
        tables=[],
        reading_order=[],
        markdown=markdown,
    )


def test_saves_markdown_in_filename_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(
        output,
        "settings",
        replace(settings, parse_output_dir=str(tmp_path / "TOTO")),
    )

    saved = output.save_parse_artifacts(_response("# parsed"), "512.pdf")

    expected = tmp_path / "TOTO" / "512" / "512.md"
    assert saved == [str(expected.resolve())]
    assert expected.read_text(encoding="utf-8") == "# parsed"


def test_reupload_replaces_only_matching_folder(monkeypatch, tmp_path):
    root = tmp_path / "TOTO"
    old = root / "512" / "old.md"
    old.parent.mkdir(parents=True)
    old.write_text("old", encoding="utf-8")
    keep = root / "other" / "keep.md"
    keep.parent.mkdir()
    keep.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(
        output,
        "settings",
        replace(settings, parse_output_dir=str(root)),
    )

    output.save_parse_artifacts(_response("# new"), "512.pdf")

    assert not old.exists()
    assert (root / "512" / "512.md").read_text(encoding="utf-8") == "# new"
    assert keep.read_text(encoding="utf-8") == "keep"


def test_missing_markdown_does_not_replace_existing_folder(monkeypatch, tmp_path):
    old = tmp_path / "TOTO" / "512" / "old.md"
    old.parent.mkdir(parents=True)
    old.write_text("old", encoding="utf-8")
    monkeypatch.setattr(
        output,
        "settings",
        replace(settings, parse_output_dir=str(tmp_path / "TOTO")),
    )

    assert output.save_parse_artifacts(_response(None), "512.pdf") == []
    assert old.read_text(encoding="utf-8") == "old"
