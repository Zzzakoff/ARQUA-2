"""Normalize documentation metadata without executing application code."""

from __future__ import annotations

import ast
from typing import Any

def documentation_from_mapping(document: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    notes: dict[str, str] = {}
    if "description" in document:
        result["description"] = document["description"]
    if "example" in document:
        result["examples"] = [document["example"]]
    examples = document.get("openapi_examples", document.get("examples"))
    if isinstance(examples, list):
        result["examples"] = examples
    elif isinstance(examples, dict):
        values = []
        for name in sorted(examples):
            example = examples[name]
            if isinstance(example, dict) and "value" in example:
                values.append(example["value"])
            else:
                notes["examples"] = "External or unresolved named examples require manual review"
        result["examples"] = values
    if notes:
        result["documentation_notes"] = notes
    return result


def documentation_from_call(node: ast.AST | None, *,
                            keys=("description", "example", "examples", "openapi_examples", "json_schema_extra")) -> dict[str, Any]:
    document: dict[str, Any] = {}
    notes: dict[str, str] = {}
    for key in keys:
        value = next((kw.value for kw in node.keywords if kw.arg == key), None) if isinstance(node, ast.Call) else None
        if value is None:
            continue
        try:
            literal = ast.literal_eval(value)
        except (ValueError, TypeError, SyntaxError):
            notes["description" if key == "description" else "examples"] = f"Computed {key} could not be resolved statically"
            continue
        if key == "json_schema_extra":
            if isinstance(literal, dict):
                document.update(literal)
        else:
            document[key] = literal
    result = documentation_from_mapping(document)
    if notes:
        result["documentation_notes"] = {**result.get("documentation_notes", {}), **notes}
    return result


def apply_documentation(target: Any, values: dict[str, Any]) -> None:
    for key, value in values.items():
        if key == "documentation_notes":
            target.documentation_notes.update(value)
        else:
            setattr(target, key, value)
