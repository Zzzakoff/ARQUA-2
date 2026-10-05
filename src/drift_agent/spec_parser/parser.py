from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml

from drift_agent.errors import (
    SpecLoadError,
    SpecParseError,
    SpecValidationError,
    UnsupportedFeatureError,
    UnsupportedVersionError,
)
from drift_agent.spec_parser.resolver import SpecResolver
from drift_agent.types import (
    EndpointContract,
    FieldSchema,
    NormalizedContract,
    ParameterSchema,
    RequestBodySchema,
    ResponseSchema,
)

LOGGER = logging.getLogger(__name__)

CANONICAL_TYPE_MAP = {
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "array": "array",
    "object": "object",
    "null": "null",
}


def parse_spec(spec_path: str | Path) -> NormalizedContract:
    path = Path(spec_path)
    if not path.exists():
        raise SpecLoadError(f"Spec file not found: {path}")
    raw_text = path.read_text(encoding="utf-8")
    try:
        if path.suffix.lower() == ".json":
            document = json.loads(raw_text)
        else:
            document = yaml.safe_load(raw_text)
    except json.JSONDecodeError as exc:
        raise SpecParseError(f"Invalid JSON spec: {exc}") from exc
    except yaml.YAMLError as exc:
        raise SpecParseError(f"Invalid YAML spec: {exc}") from exc
    if not isinstance(document, dict):
        raise SpecValidationError("Spec root must be a mapping")
    _validate_document(document)
    resolver = SpecResolver(document, path)
    inline_document = resolver.resolve_document()
    endpoints = _extract_endpoints(inline_document)
    metadata = {
        "title": inline_document["info"]["title"],
        "version": inline_document["info"]["version"],
        "servers": inline_document.get("servers", []),
        "spec_path": str(path),
    }
    return NormalizedContract(endpoints=endpoints, source="spec", metadata=metadata)


def _validate_document(document: dict[str, Any]) -> None:
    for key in ("openapi", "info", "paths"):
        if key not in document:
            raise SpecValidationError(f"Missing required OpenAPI key: {key}")
    version = str(document["openapi"])
    if version.startswith("2."):
        raise UnsupportedVersionError("Swagger/OpenAPI 2.x is not supported")
    if not version.startswith("3."):
        raise UnsupportedVersionError(f"Unsupported OpenAPI version: {version}")


def _extract_endpoints(document: dict[str, Any]) -> dict[str, EndpointContract]:
    endpoints: dict[str, EndpointContract] = {}
    for raw_path, path_item in (document.get("paths") or {}).items():
        normalized_path = _normalize_path(raw_path)
        if not isinstance(path_item, dict):
            continue
        shared_parameters = path_item.get("parameters", [])
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete", "head", "options", "trace"}:
                continue
            if not isinstance(operation, dict):
                continue
            try:
                endpoint = _build_endpoint(method, normalized_path, operation, shared_parameters)
            except UnsupportedFeatureError as exc:
                LOGGER.warning("Skipping %s %s: %s", method.upper(), normalized_path, exc)
                continue
            endpoints[f"{method.upper()} {normalized_path}"] = endpoint
    return endpoints


def _build_endpoint(
    method: str,
    normalized_path: str,
    operation: dict[str, Any],
    shared_parameters: list[dict[str, Any]],
) -> EndpointContract:
    parameter_docs = [*shared_parameters, *(operation.get("parameters") or [])]
    parameters = []
    for item in parameter_docs:
        if not isinstance(item, dict):
            continue
        schema = item.get("schema") or {}
        field = _normalize_schema(
            schema,
            name=str(item.get("name", "value")),
            required=bool(item.get("required", item.get("in") == "path")),
        )
        parameters.append(
            ParameterSchema(
                name=str(item.get("name")),
                location=item.get("in", "query"),
                required=bool(item.get("required", item.get("in") == "path")),
                schema=field,
            )
        )
    request_body = None
    if operation.get("requestBody"):
        body_doc = operation["requestBody"]
        required = bool(body_doc.get("required", False))
        content = body_doc.get("content") or {}
        content_type, payload = _pick_content(content)
        if payload is not None:
            schema = _normalize_schema(payload.get("schema") or {"type": "object"}, name="body", required=True)
            request_body = RequestBodySchema(required=required, content_type=content_type, schema=schema)
    responses = {}
    for status_code, response_doc in (operation.get("responses") or {}).items():
        if not isinstance(response_doc, dict):
            continue
        content_type, payload = _pick_content(response_doc.get("content") or {})
        schema = None
        if payload is not None and payload.get("schema") is not None:
            schema = _normalize_schema(payload["schema"], name="response", required=True)
        responses[str(status_code)] = ResponseSchema(
            status_code=str(status_code),
            content_type=content_type,
            schema=schema,
        )
    return EndpointContract(
        method=method.upper(),
        path=normalized_path,
        parameters=parameters,
        request_body=request_body,
        responses=responses,
        tags=list(operation.get("tags") or []),
    )


def _pick_content(content: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    if not content:
        return "application/json", None
    if "application/json" in content:
        return "application/json", content["application/json"]
    first_key = next(iter(content))
    return first_key, content[first_key]


def _normalize_schema(schema: dict[str, Any] | None, name: str, required: bool) -> FieldSchema:
    if not schema:
        return FieldSchema(name=name, type="unknown", required=required)
    if "allOf" in schema:
        schema = _flatten_allof(schema)
    if "anyOf" in schema or "oneOf" in schema:
        schema = _flatten_union(schema)
    schema_type = _determine_type(schema)
    nullable = bool(schema.get("nullable", False))
    analysis_note = schema.get("_analysis_note")
    if isinstance(schema.get("type"), list):
        nullable = "null" in schema["type"]
        non_null_types = set(schema["type"]) - {"null"}
        schema_type = next(iter(non_null_types)) if len(non_null_types) == 1 else "null" if not non_null_types else "unknown"
        if len(non_null_types) > 1:
            analysis_note = "Multiple OpenAPI schema types require manual review"
    field = FieldSchema(
        name=name,
        type=CANONICAL_TYPE_MAP.get(schema_type, schema_type or "unknown"),
        format=schema.get("format"),
        required=required,
        nullable=nullable,
        enum=list(schema.get("enum")) if isinstance(schema.get("enum"), list) else None,
        description=schema.get("description"),
        analysis_note=analysis_note,
    )
    if field.type == "array":
        field.items = _normalize_schema(schema.get("items") or {}, name=f"{name}[]", required=True)
    elif field.type == "object":
        properties: dict[str, FieldSchema] = {}
        required_props = set(schema.get("required") or [])
        for prop_name, prop_schema in (schema.get("properties") or {}).items():
            if prop_schema is None:
                continue
            properties[prop_name] = _normalize_schema(
                prop_schema,
                name=prop_name,
                required=prop_name in required_props,
            )
        field.properties = properties
    return field


def _flatten_allof(schema: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
    for subschema in schema.get("allOf", []):
        candidate = _flatten_union(_flatten_allof(subschema) if "allOf" in subschema else subschema)
        if candidate.get("type", "object") != "object":
            return {"type": "unknown", "_analysis_note": "Non-object allOf requires manual review"}
        for key, value in candidate.items():
            if key == "properties":
                for prop_name, prop_value in value.items():
                    if prop_name in merged["properties"] and merged["properties"][prop_name] != prop_value:
                        LOGGER.warning("allOf conflict on property '%s'; first definition wins", prop_name)
                        merged["_analysis_note"] = f"Conflicting allOf definitions for {prop_name}"
                        continue
                    merged["properties"][prop_name] = prop_value
            elif key == "required":
                merged["required"] = sorted(set([*merged["required"], *value]))
            elif key not in merged:
                merged[key] = value
    return merged


def _flatten_union(schema: dict[str, Any]) -> dict[str, Any]:
    variants = schema.get("anyOf") or schema.get("oneOf") or []
    if not variants:
        return schema
    normalized: list[dict[str, Any]] = []
    for variant in variants:
        candidate = _flatten_allof(variant) if "allOf" in variant else variant
        normalized.append(candidate)
    non_null_types = {_determine_type(item) for item in normalized if _determine_type(item) != "null"}
    has_null = any(_determine_type(item) == "null" for item in normalized)
    non_null_variants = [item for item in normalized if _determine_type(item) != "null"]
    if len(non_null_types) == 1 and len(non_null_variants) == 1:
        base = next(item for item in normalized if _determine_type(item) != "null")
        base = dict(base)
        if has_null:
            base["nullable"] = True
        return base
    LOGGER.warning("Unresolvable anyOf/oneOf encountered")
    return {"type": "unknown", "_analysis_note": "Multiple anyOf/oneOf variants require manual review"}


def _determine_type(schema: dict[str, Any]) -> str:
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        for item in schema_type:
            if item != "null":
                return item
        return "null"
    if schema_type:
        return schema_type
    if "properties" in schema:
        return "object"
    if "items" in schema:
        return "array"
    return "unknown"


def _normalize_path(path: str) -> str:
    if not path.startswith("/"):
        path = f"/{path}"
    while "//" in path:
        path = path.replace("//", "/")
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return path

