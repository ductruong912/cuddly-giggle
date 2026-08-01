"""Derive an OpenAI strict-mode JSON Schema from a Pydantic model.

Strict structured outputs impose rules ordinary JSON Schema does not: every
object must forbid additional properties, every declared property must be
required, and a handful of keywords are rejected outright. Getting this wrong
fails at call time with an opaque 400, so ``assert_strict_schema`` runs at
import and turns a bad schema into a startup error instead.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


# Rejected by the API in strict mode.
UNSUPPORTED_KEYWORDS = frozenset(
    {"allOf", "not", "dependentRequired", "dependentSchemas", "if", "then", "else"}
)
# Annotations Pydantic adds that carry no meaning for generation. "default" is
# meaningless once every property is required, and both are dropped to keep the
# schema close to the hand-written one this replaced.
_STRIPPED_KEYWORDS = ("title", "default")


def to_strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Build a strict-mode-compliant JSON Schema for ``model``."""
    schema = model.model_json_schema()
    _harden(schema)
    assert_strict_schema(schema)
    return schema


def _harden(node: Any) -> None:
    """Recursively enforce the strict-mode object rules, in place."""
    if isinstance(node, list):
        for item in node:
            _harden(item)
        return
    if not isinstance(node, dict):
        return

    for keyword in _STRIPPED_KEYWORDS:
        node.pop(keyword, None)

    if node.get("type") == "object" or "properties" in node:
        node["additionalProperties"] = False
        properties = node.get("properties")
        if isinstance(properties, dict):
            # Every declared property must be required; optionality is expressed
            # by the field's type being a union with null, not by omission.
            node["required"] = list(properties.keys())

    for value in node.values():
        _harden(value)


def assert_strict_schema(schema: dict[str, Any], path: str = "$") -> None:
    """Raise ValueError if ``schema`` would be rejected in strict mode."""
    for problem in _strict_schema_problems(schema, path):
        raise ValueError(f"Schema is not valid for OpenAI strict mode: {problem}")


def _strict_schema_problems(node: Any, path: str) -> list[str]:
    problems: list[str] = []
    if isinstance(node, list):
        for index, item in enumerate(node):
            problems.extend(_strict_schema_problems(item, f"{path}[{index}]"))
        return problems
    if not isinstance(node, dict):
        return problems

    for keyword in sorted(UNSUPPORTED_KEYWORDS & node.keys()):
        problems.append(f"{path} uses unsupported keyword {keyword!r}")

    if node.get("type") == "object" or "properties" in node:
        if node.get("additionalProperties") is not False:
            problems.append(f"{path} must set additionalProperties to false")
        properties = node.get("properties") or {}
        required = set(node.get("required") or ())
        missing = sorted(set(properties) - required)
        if missing:
            problems.append(f"{path} omits required propert(ies): {', '.join(missing)}")

    for key, value in node.items():
        if key in {"properties", "$defs"} and isinstance(value, dict):
            for name, child in value.items():
                problems.extend(_strict_schema_problems(child, f"{path}.{name}"))
        else:
            problems.extend(_strict_schema_problems(value, f"{path}.{key}"))
    return problems
