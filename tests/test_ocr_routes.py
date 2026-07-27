from __future__ import annotations

from api.application import create_app


def test_application_exposes_only_replacement_extract_routes() -> None:
    paths = {route.path for route in create_app().routes}

    assert {"/v1/extract/local", "/v1/extract/online"} <= paths
    assert "/v1/doc/extract" not in paths
    assert "/v1/doc/extract-fast" not in paths
    assert "/v1/extract/ocr" not in paths
