from __future__ import annotations

from api.application import create_app


def test_main_module_imports() -> None:
    import main  # noqa: F401


def test_application_exposes_extract_routes_and_debug_ocr_route() -> None:
    paths = {route.path for route in create_app().routes}

    assert {"/v1/extract/local", "/v1/extract/online"} <= paths
    assert "/v1/doc/ocr" in paths
    assert "/v1/doc/extract" not in paths
    assert "/v1/doc/extract-fast" not in paths
    assert "/v1/extract/ocr" not in paths
