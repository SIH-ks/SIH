"""Strict JSON Schema derivation from the LLM wire contract.

Anthropic's strict tool use (``strict: true`` on the tool definition) guarantees the
model's ``tool_use.input`` validates against the schema exactly, but it requires every
object in the schema to declare ``"additionalProperties": false`` and list every one
of its properties as ``required`` (nullable fields simply have ``null`` in their type
union -- "required" here means "always present," not "always non-null," which is
exactly the semantics :mod:`adhikar.schemas.llm_contract` wants).

Pydantic's ``model_json_schema()`` does not set either of those by itself, even with
``model_config = ConfigDict(extra="forbid")`` -- ``extra="forbid"`` controls Python-side
validation, not the emitted JSON Schema. This module walks the generated schema
(including everything under ``$defs``, since nested Pydantic models are emitted there
and referenced by ``$ref``) and adds both, recursively.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

__all__ = ["build_strict_tool_schema"]


def _strictify(node: Any) -> None:
    """Recursively enforce strict-mode object requirements, in place."""
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"].keys())
        for value in node.values():
            _strictify(value)
    elif isinstance(node, list):
        for item in node:
            _strictify(item)


def build_strict_tool_schema(
    model: type[BaseModel],
    *,
    tool_name: str,
    description: str,
) -> dict[str, Any]:
    """Build a strict-mode tool definition from a Pydantic model.

    The returned dict is ready to place directly in the ``tools`` list of a
    ``messages.create`` call, with ``strict: True`` already set.
    """
    schema = model.model_json_schema()
    schema.pop("title", None)
    schema.pop("description", None)
    _strictify(schema)

    return {
        "name": tool_name,
        "description": description,
        "strict": True,
        "input_schema": schema,
    }
