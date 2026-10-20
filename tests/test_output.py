"""Request isolation, atomic artifact writes and safe output paths."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

from core.domain.schemas import ParseResponse
from services import output


@pytest.fixture
def output_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(output, "settings", SimpleNamespace(parse_output_dir=tmp_path))
    return tmp_path


def test_concurrent_same_name_uploads_keep_matching_artifact_pairs(
    output_root: Path, parse_response: ParseResponse,
) -> None:
    legacy_file = output_root / "order" / "order.md"
    legacy_file.parent.mkdir()
    legacy_file.write_text("existing artifact", encoding="utf-8")
    both_markdowns_saved = Barrier(2)

    def save_request(request_id: str) -> tuple[Path, Path]:
        response = parse_response.model_copy(
            update={"request_id": request_id, "markdown": f"# {request_id}"}
        )
        markdown_path = Path(output.save_parse_artifacts(response, "order.pdf")[0])
        both_markdowns_saved.wait(timeout=5)
        json_path = Path(output.save_extraction_artifacts(
            {"po_number": request_id}, "order.pdf", request_id=request_id,
        )[0])
        return markdown_path, json_path

    request_ids = ("req_first", "req_second")
    with ThreadPoolExecutor(max_workers=2) as executor:
        saved_pairs = list(executor.map(save_request, request_ids))

    for request_id, (markdown_path, json_path) in zip(request_ids, saved_pairs):
        assert markdown_path.parent == json_path.parent == output_root / request_id
        assert markdown_path.read_text(encoding="utf-8") == f"# {request_id}"
        assert json.loads(json_path.read_text(encoding="utf-8")) == {"po_number": request_id}
        assert {path.name for path in markdown_path.parent.iterdir()} == {"order.md", "order.json"}
    assert legacy_file.read_text(encoding="utf-8") == "existing artifact"


def test_atomic_replace_failure_preserves_previous_complete_artifact(
    output_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = {"po_number": "old", "items": ["complete"]}
    saved_path = Path(output.save_extraction_artifacts(
        existing, "order.pdf", request_id="req_retry",
    )[0])

    def fail_replace(temporary_path: Path, target: Path) -> None:
        assert target == saved_path
        assert json.loads(target.read_text(encoding="utf-8")) == existing
        assert json.loads(Path(temporary_path).read_text(encoding="utf-8")) == {"po_number": "new"}
        raise OSError("destination locked")

    monkeypatch.setattr(output.os, "replace", fail_replace)
    with pytest.raises(OSError, match="destination locked"):
        output.save_extraction_artifacts({"po_number": "new"}, "order.pdf", request_id="req_retry")

    assert json.loads(saved_path.read_text(encoding="utf-8")) == existing
    assert list((output_root / "req_retry").iterdir()) == [saved_path]


@pytest.mark.parametrize(
    ("filename", "expected_stem"),
    [
        ("../../CON.pdf", "document_CON"),
        (r"C:\uploads\NUL.txt", "document_NUL"),
        ("CON.extra.pdf", "document_CON.extra"),
        ("LPT¹.pdf", "document_LPT¹"),
        ("../bad:na?me\x01.pdf", "badname"),
        ("x" * 400 + ".pdf", "x" * 80),
        ("🚀" * 100 + ".pdf", "🚀" * 40),
        ("文" * 100 + ".pdf", "文" * 53),
        (".pdf", "pdf"),
        (" .pdf", "document"),
    ],
)
def test_uploaded_names_remain_safe_display_names(
    output_root: Path, parse_response: ParseResponse, filename: str, expected_stem: str,
) -> None:
    saved_path = Path(output.save_parse_artifacts(parse_response, filename)[0])
    assert saved_path == output_root / parse_response.request_id / f"{expected_stem}.md"
    assert saved_path.read_text(encoding="utf-8") == parse_response.markdown


@pytest.mark.parametrize("filename", ["🚀" * 100 + ".pdf", "CON." + "🚀" * 100 + ".pdf"])
def test_long_unicode_names_leave_room_for_atomic_temporary_files(
    output_root: Path, parse_response: ParseResponse, monkeypatch: pytest.MonkeyPatch, filename: str,
) -> None:
    replace = output.os.replace
    temporary_names: list[str] = []

    def check_replace(temporary_path: Path, target: Path) -> None:
        assert temporary_path.parent == target.parent == output_root / parse_response.request_id
        assert len(temporary_path.name.encode("utf-8")) <= 255
        assert len(target.name.encode("utf-8")) <= 255
        temporary_names.append(temporary_path.name)
        replace(temporary_path, target)

    monkeypatch.setattr(output.os, "replace", check_replace)
    saved_path = Path(output.save_parse_artifacts(parse_response, filename)[0])
    assert len(temporary_names) == 1
    assert saved_path.read_text(encoding="utf-8") == parse_response.markdown
    assert list(saved_path.parent.iterdir()) == [saved_path]


@pytest.mark.parametrize(
    "request_id",
    ["", "../escape", "..", r"req\escape", "C:escape", "CON", "lpt1", "x" * 129],
)
def test_unsafe_request_ids_cannot_create_artifact_directories(
    output_root: Path, request_id: str,
) -> None:
    with pytest.raises(ValueError, match="request_id"):
        output.save_extraction_artifacts({}, "order.pdf", request_id=request_id)
    assert list(output_root.iterdir()) == []
