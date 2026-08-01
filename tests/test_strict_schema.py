"""The extraction schema is generated from the model, so the two cannot drift."""
from __future__ import annotations

import pytest
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, ConfigDict

from core.domain.purchase_order import PurchaseOrder
from core.domain.strict_schema import (
    UNSUPPORTED_KEYWORDS,
    assert_strict_schema,
    to_strict_json_schema,
)
from core.prompts.prompt import EXTRACTION_JSON_SCHEMA


def test_the_shipped_schema_is_strict_mode_valid() -> None:
    """A malformed schema must be a startup error, not a per-request 400."""
    assert_strict_schema(EXTRACTION_JSON_SCHEMA)


def test_the_shipped_schema_is_generated_from_the_model() -> None:
    assert EXTRACTION_JSON_SCHEMA == to_strict_json_schema(PurchaseOrder)


def test_every_object_forbids_extra_properties() -> None:
    def walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(EXTRACTION_JSON_SCHEMA)


def test_every_property_is_required() -> None:
    """Strict mode has no optional keys; nullability is expressed in the type."""

    def walk(node: object) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                assert set(node.get("required", [])) == set(properties)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(EXTRACTION_JSON_SCHEMA)


def test_the_line_item_fields_survive_generation() -> None:
    item_schema = EXTRACTION_JSON_SCHEMA["$defs"]["PurchaseOrderItem"]

    assert set(item_schema["properties"]) == {
        "toto_number",
        "customer_number",
        "quantity",
        "unit_price",
        "extension",
    }


def test_field_descriptions_reach_the_model() -> None:
    """The descriptions are the only per-field instruction the model receives."""
    item_schema = EXTRACTION_JSON_SCHEMA["$defs"]["PurchaseOrderItem"]

    assert item_schema["properties"]["extension"]["description"]
    assert EXTRACTION_JSON_SCHEMA["properties"]["po_date"]["description"]


@pytest.mark.parametrize("keyword", sorted(UNSUPPORTED_KEYWORDS))
def test_unsupported_keywords_are_caught(keyword: str) -> None:
    with pytest.raises(ValueError, match=keyword):
        assert_strict_schema(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"a": {"type": "string"}},
                "required": ["a"],
                keyword: {},
            }
        )


def test_a_missing_required_key_is_caught() -> None:
    with pytest.raises(ValueError, match="required"):
        assert_strict_schema(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
                "required": ["a"],
            }
        )


def test_open_objects_are_caught() -> None:
    with pytest.raises(ValueError, match="additionalProperties"):
        assert_strict_schema(
            {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        )


def test_generation_hardens_a_permissive_model() -> None:
    """Defaults make a field optional, which strict mode does not allow."""

    class Permissive(BaseModel):
        model_config = ConfigDict(extra="allow")

        name: str = "unnamed"

    schema = to_strict_json_schema(Permissive)

    assert schema["additionalProperties"] is False
    assert schema["required"] == ["name"]
    assert "default" not in schema["properties"]["name"]
