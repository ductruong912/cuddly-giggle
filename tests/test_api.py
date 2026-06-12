from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.dependencies import get_orchestrator
from app.application import app
from app.domain.schemas import LangHint, ParseDecision, ParseResponse, QualityFlags
import app.services.output.artifacts as artifacts


class StubOrchestrator:
    def parse(self, input_path: str, options):  # type: ignore[no-untyped-def]
        return ParseResponse(
            request_id="req_test",
            decision=ParseDecision(status="pass", reason="ok"),
            pages=[],
            blocks=[],
            tables=[],
            reading_order=[],
            quality_flags=QualityFlags(),
            markdown="# Parsed",
            review_queued=False,
            review_reason=None,
        )


def _unlink_artifact_variants(stem: str) -> None:
    output_dir = Path("outputs")
    for path in [output_dir / f"{stem}.md"] + [output_dir / f"{stem} ({idx}).md" for idx in range(2, 50)]:
        path.unlink(missing_ok=True)


def test_parse_api_contract(monkeypatch) -> None:
    app.dependency_overrides[get_orchestrator] = lambda: StubOrchestrator()
    client = TestClient(app)
    output_stem = "sample_contract"
    _unlink_artifact_variants(output_stem)

    try:
        resp = client.post(
            "/v1/doc/parse",
            files={"file": (f"{output_stem}.png", b"not-real-image", "image/png")},
            data={"enable_fallback": "true"},
        )
    finally:
        app.dependency_overrides.clear()
        _unlink_artifact_variants(output_stem)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert resp.text == "# Parsed"


def test_parse_api_does_not_expose_internal_form_fields() -> None:
    schema = app.openapi()
    request_body_ref = schema["paths"]["/v1/doc/parse"]["post"]["requestBody"]["content"]["multipart/form-data"][
        "schema"
    ]["$ref"]
    component_name = request_body_ref.rsplit("/", 1)[-1]

    form_properties = schema["components"]["schemas"][component_name]["properties"]

    assert "lang_hint" not in form_properties
    assert "output_basename" not in form_properties
    assert list(LangHint) == [LangHint.auto]


def test_parse_api_enable_fallback_defaults_to_crash_recovery() -> None:
    schema = app.openapi()
    request_body_ref = schema["paths"]["/v1/doc/parse"]["post"]["requestBody"]["content"]["multipart/form-data"][
        "schema"
    ]["$ref"]
    component_name = request_body_ref.rsplit("/", 1)[-1]

    form_properties = schema["components"]["schemas"][component_name]["properties"]

    assert form_properties["enable_fallback"]["default"] is True


def test_parse_api_auto_save_output(monkeypatch) -> None:
    app.dependency_overrides[get_orchestrator] = lambda: StubOrchestrator()
    client = TestClient(app)
    expected = Path("outputs/sample_doc.md").resolve()
    _unlink_artifact_variants("sample_doc")

    try:
        resp = client.post(
            "/v1/doc/parse",
            files={"file": ("sample_doc.png", b"not-real-image", "image/png")},
            data={
                "enable_fallback": "false",
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert expected.exists()
    assert expected.read_text(encoding="utf-8") == "# Parsed"
    _unlink_artifact_variants("sample_doc")


def test_parse_api_ignores_legacy_output_basename_field(monkeypatch, tmp_path) -> None:
    app.dependency_overrides[get_orchestrator] = lambda: StubOrchestrator()
    monkeypatch.setattr(artifacts, "settings", SimpleNamespace(parse_output_dir=str(tmp_path)))
    client = TestClient(app)

    try:
        resp = client.post(
            "/v1/doc/parse",
            files={"file": ("sample_upload.pdf", b"not-real-pdf", "application/pdf")},
            data={"enable_fallback": "false", "output_basename": "string"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert (tmp_path / "sample_upload.md").exists()
    assert not (tmp_path / "string.md").exists()


def test_parse_api_does_not_write_json_when_legacy_output_format_is_sent(monkeypatch) -> None:
    app.dependency_overrides[get_orchestrator] = lambda: StubOrchestrator()
    client = TestClient(app)
    expected_md = Path("outputs/sample_doc_md.md").resolve()
    unexpected_json = Path("outputs/sample_doc_md.json").resolve()
    _unlink_artifact_variants("sample_doc_md")
    unexpected_json.unlink(missing_ok=True)

    try:
        resp = client.post(
            "/v1/doc/parse",
            files={"file": ("sample_doc_md.png", b"not-real-image", "image/png")},
            data={
                "output_format": "json",
                "enable_fallback": "false",
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert expected_md.exists()
    assert not unexpected_json.exists()
    _unlink_artifact_variants("sample_doc_md")


def test_parse_api_accepts_word_uploads(monkeypatch) -> None:
    app.dependency_overrides[get_orchestrator] = lambda: StubOrchestrator()
    client = TestClient(app)
    _unlink_artifact_variants("sample_word_docx")
    _unlink_artifact_variants("sample_word_doc")

    try:
        docx_resp = client.post(
            "/v1/doc/parse",
            files={
                "file": (
                    "sample_word_docx.docx",
                    b"not-a-real-docx-because-orchestrator-is-stubbed",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
            data={"enable_fallback": "false"},
        )
        doc_resp = client.post(
            "/v1/doc/parse",
            files={"file": ("sample_word_doc.doc", b"legacy-doc", "application/msword")},
            data={"enable_fallback": "false"},
        )
    finally:
        app.dependency_overrides.clear()
        _unlink_artifact_variants("sample_word_docx")
        _unlink_artifact_variants("sample_word_doc")

    assert docx_resp.status_code == 200
    assert docx_resp.text == "# Parsed"
    assert doc_resp.status_code == 200
    assert doc_resp.text == "# Parsed"


def test_parse_api_accepts_excel_uploads(monkeypatch) -> None:
    app.dependency_overrides[get_orchestrator] = lambda: StubOrchestrator()
    client = TestClient(app)
    _unlink_artifact_variants("sample_excel_xlsx")
    _unlink_artifact_variants("sample_excel_xls")

    try:
        xlsx_resp = client.post(
            "/v1/doc/parse",
            files={
                "file": (
                    "sample_excel_xlsx.xlsx",
                    b"not-a-real-xlsx-because-orchestrator-is-stubbed",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            data={"enable_fallback": "false"},
        )
        xls_resp = client.post(
            "/v1/doc/parse",
            files={"file": ("sample_excel_xls.xls", b"legacy-xls", "application/vnd.ms-excel")},
            data={"enable_fallback": "false"},
        )
    finally:
        app.dependency_overrides.clear()
        _unlink_artifact_variants("sample_excel_xlsx")
        _unlink_artifact_variants("sample_excel_xls")

    assert xlsx_resp.status_code == 200
    assert xlsx_resp.text == "# Parsed"
    assert xls_resp.status_code == 200
    assert xls_resp.text == "# Parsed"
