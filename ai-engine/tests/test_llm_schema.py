"""Strict-mode JSON Schema derivation for the Vision LLM tool call."""

from __future__ import annotations

from typing import Any

from adhikar.llm.schema import build_strict_tool_schema
from adhikar.schemas.llm_contract import LlmExtraction


def _find_object_nodes(node: Any) -> list[dict]:
    found: list[dict] = []
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            found.append(node)
        for value in node.values():
            found.extend(_find_object_nodes(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_find_object_nodes(item))
    return found


def test_tool_definition_shape() -> None:
    tool = build_strict_tool_schema(
        LlmExtraction, tool_name="extract_land_record", description="Extract a land record."
    )
    assert tool["name"] == "extract_land_record"
    assert tool["strict"] is True
    assert "input_schema" in tool


def test_every_object_node_is_strict() -> None:
    tool = build_strict_tool_schema(LlmExtraction, tool_name="x", description="d")
    schema = tool["input_schema"]
    object_nodes = _find_object_nodes(schema)
    assert len(object_nodes) > 5  # sanity: the schema really is nested

    for node in object_nodes:
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"].keys())
