from __future__ import annotations

from drift_agent.diff_engine.classifier import make_drift_id
from drift_agent.types import DriftCategory, DriftItem, EndpointContract, FieldSchema, NormalizedContract


def compute_drift(spec_contract: NormalizedContract, code_contract: NormalizedContract) -> list[DriftItem]:
    drift_items: list[DriftItem] = []
    diagnostics = code_contract.metadata.get("diagnostics", [])
    incomplete_routes = any(item.get("scope") == "routes" for item in diagnostics)
    for diagnostic in diagnostics:
        item = _limitation("*", f"source.{diagnostic.get('source_file')}:{diagnostic.get('source_line')}", diagnostic["message"])
        item.source_file = diagnostic.get("source_file")
        item.source_line = diagnostic.get("source_line")
        drift_items.append(item)
    spec_endpoints = set(spec_contract.endpoints)
    code_endpoints = set(code_contract.endpoints)
    for endpoint in sorted(spec_endpoints - code_endpoints):
        if incomplete_routes:
            drift_items.append(_limitation(endpoint, "endpoint", "Endpoint was not found, but route analysis is incomplete; absence is not confirmed"))
        else:
            drift_items.append(_build_item(endpoint, DriftCategory.MISSING_ENDPOINT, "endpoint", "Endpoint declared in spec but missing in code", endpoint, None, "error"))
    for endpoint in sorted(code_endpoints - spec_endpoints):
        if incomplete_routes:
            drift_items.append(_limitation(endpoint, "endpoint", "Route registration is incomplete; the effective path requires review"))
        else:
            drift_items.append(_build_item(endpoint, DriftCategory.GHOST_ENDPOINT, "endpoint", "Endpoint exists in code but is missing from spec", None, endpoint, "warning"))
    for endpoint in sorted(spec_endpoints & code_endpoints):
        drift_items.extend(_compare_endpoint(endpoint, spec_contract.endpoints[endpoint], code_contract.endpoints[endpoint]))
    for item in drift_items:
        code_endpoint = code_contract.endpoints.get(item.endpoint)
        if code_endpoint is not None:
            item.source_file = code_endpoint.source_file
            item.source_line = code_endpoint.source_line
    # Multiple diagnostics at a source line can have different messages.
    seen: set[str] = set()
    for item in drift_items:
        if item.id in seen:
            item.id = make_drift_id(item.endpoint, f"{item.location}|{item.detail}", item.category)
        seen.add(item.id)
    return drift_items


def _compare_endpoint(endpoint: str, spec_endpoint: EndpointContract, code_endpoint: EndpointContract) -> list[DriftItem]:
    items: list[DriftItem] = []
    for scope, compare in (("parameters", _compare_parameters), ("request_body", _compare_request_bodies), ("responses", _compare_responses)):
        note = code_endpoint.analysis_notes.get(scope)
        if note:
            items.append(_limitation(endpoint, scope, note))
        else:
            items.extend(compare(endpoint, spec_endpoint, code_endpoint))
    return items


def _compare_parameters(endpoint: str, spec_endpoint: EndpointContract, code_endpoint: EndpointContract) -> list[DriftItem]:
    items: list[DriftItem] = []
    def parameter_key(param):
        return (param.name.lower() if param.location == "header" else param.name, param.location)
    spec_params = {parameter_key(param): param for param in spec_endpoint.parameters}
    code_params = {parameter_key(param): param for param in code_endpoint.parameters}
    for key in sorted(spec_params.keys() - code_params.keys()):
        items.append(
            _build_item(
                endpoint,
                DriftCategory.PARAMETER_DRIFT,
                f"parameters.{key[0]}",
                f"Parameter '{key[0]}' is present in spec but missing in code",
                f"{key[1]} parameter",
                None,
                "error",
            )
        )
    for key in sorted(code_params.keys() - spec_params.keys()):
        items.append(
            _build_item(
                endpoint,
                DriftCategory.PARAMETER_DRIFT,
                f"parameters.{key[0]}",
                f"Parameter '{key[0]}' is present in code but missing in spec",
                None,
                f"{key[1]} parameter",
                "warning",
            )
        )
    for key in sorted(spec_params.keys() & code_params.keys()):
        if spec_params[key].required != code_params[key].required:
            items.append(_build_item(endpoint, DriftCategory.REQUIRED_DRIFT, f"parameters.{key[0]}.required", "Parameter required flag differs", str(spec_params[key].required), str(code_params[key].required), "warning"))
        items.extend(
            _compare_schemas(
                endpoint,
                f"parameters.{key[0]}",
                spec_params[key].schema,
                code_params[key].schema,
            )
        )
    return items


def _compare_request_bodies(endpoint: str, spec_endpoint: EndpointContract, code_endpoint: EndpointContract) -> list[DriftItem]:
    if spec_endpoint.request_body and not code_endpoint.request_body:
        return [_build_item(endpoint, DriftCategory.DESTRUCTIVE_DRIFT, "request_body", "Spec defines a request body but code does not", "request body", None, "error")]
    if code_endpoint.request_body and not spec_endpoint.request_body:
        return [_build_item(endpoint, DriftCategory.ADDITIVE_DRIFT, "request_body", "Code accepts a request body that spec does not define", None, "request body", "warning")]
    if spec_endpoint.request_body and code_endpoint.request_body:
        items = _compare_schemas(endpoint, "request_body.schema", spec_endpoint.request_body.schema, code_endpoint.request_body.schema)
        if spec_endpoint.request_body.required != code_endpoint.request_body.required:
            items.append(_build_item(endpoint, DriftCategory.REQUIRED_DRIFT, "request_body.required", "Request body required flag differs", str(spec_endpoint.request_body.required), str(code_endpoint.request_body.required), "warning"))
        if spec_endpoint.request_body.content_type != code_endpoint.request_body.content_type:
            items.append(
                _build_item(
                    endpoint,
                    DriftCategory.PARAMETER_DRIFT,
                    "request_body.content_type",
                    "Request body content type differs between spec and code",
                    spec_endpoint.request_body.content_type,
                    code_endpoint.request_body.content_type,
                    "warning",
                )
            )
        return items
    return []


def _compare_responses(endpoint: str, spec_endpoint: EndpointContract, code_endpoint: EndpointContract) -> list[DriftItem]:
    items: list[DriftItem] = []
    spec_codes = set(spec_endpoint.responses)
    code_codes = set(code_endpoint.responses)
    for status in sorted(spec_codes - code_codes):
        if status == "422":
            continue
        items.append(_build_item(endpoint, DriftCategory.STATUS_CODE_DRIFT, f"response.{status}", f"Status code {status} documented in spec but missing in code", status, None, "warning"))
    for status in sorted(code_codes - spec_codes):
        if status == "422":
            continue
        items.append(_build_item(endpoint, DriftCategory.STATUS_CODE_DRIFT, f"response.{status}", f"Status code {status} returned by code but missing in spec", None, status, "info"))
    for status in sorted(spec_codes & code_codes):
        if status == "422":
            continue
        items.extend(
            _compare_schemas(
                endpoint,
                f"response.{status}.schema",
                spec_endpoint.responses[status].schema,
                code_endpoint.responses[status].schema,
            )
        )
    return items


def _compare_schemas(endpoint: str, location: str, spec_schema: FieldSchema | None, code_schema: FieldSchema | None) -> list[DriftItem]:
    items: list[DriftItem] = []
    notes = [schema.analysis_note or "Schema type is unknown" for schema in (spec_schema, code_schema) if schema is not None and (schema.analysis_note or schema.type == "unknown")]
    if notes:
        return [_limitation(endpoint, location, "; ".join(dict.fromkeys(notes)))]
    if spec_schema is None and code_schema is None:
        return items
    if spec_schema is not None and code_schema is None:
        return [_build_item(endpoint, DriftCategory.DESTRUCTIVE_DRIFT, location, "Spec defines a schema but code does not", _schema_summary(spec_schema), None, "error")]
    if code_schema is not None and spec_schema is None:
        return [_build_item(endpoint, DriftCategory.ADDITIVE_DRIFT, location, "Code defines a schema but spec does not", None, _schema_summary(code_schema), "warning")]
    assert spec_schema is not None and code_schema is not None
    if spec_schema.type == "number" and code_schema.type == "integer":
        pass
    elif spec_schema.type != code_schema.type:
        return [_build_item(endpoint, DriftCategory.TYPE_DRIFT, location, f"Type mismatch: spec={spec_schema.type}, code={code_schema.type}", _schema_summary(spec_schema), _schema_summary(code_schema), "error")]
    if spec_schema.nullable != code_schema.nullable:
        severity = "error" if not spec_schema.nullable and code_schema.nullable else "warning"
        items.append(_build_item(endpoint, DriftCategory.NULLABILITY_DRIFT, location, "Nullability differs between spec and code", str(spec_schema.nullable), str(code_schema.nullable), severity))
    if spec_schema.enum != code_schema.enum and (spec_schema.enum or code_schema.enum):
        items.append(_build_item(endpoint, DriftCategory.TYPE_DRIFT, location, "Enum values differ between spec and code", str(spec_schema.enum), str(code_schema.enum), "warning"))
    if spec_schema.format != code_schema.format and spec_schema.type == code_schema.type:
        items.append(_build_item(endpoint, DriftCategory.TYPE_DRIFT, location, "Format differs between spec and code", str(spec_schema.format), str(code_schema.format), "info"))
    if spec_schema.type == "object":
        spec_props = spec_schema.properties or {}
        code_props = code_schema.properties or {}
        for prop in sorted(spec_props.keys() - code_props.keys()):
            items.append(_build_item(endpoint, DriftCategory.DESTRUCTIVE_DRIFT, f"{location}.{prop}", f"Field '{prop}' is documented in spec but missing in code", _schema_summary(spec_props[prop]), None, "error"))
        for prop in sorted(code_props.keys() - spec_props.keys()):
            items.append(_build_item(endpoint, DriftCategory.ADDITIVE_DRIFT, f"{location}.{prop}", f"Field '{prop}' is returned by code but missing in spec", None, _schema_summary(code_props[prop]), "warning"))
        for prop in sorted(spec_props.keys() & code_props.keys()):
            if spec_props[prop].required != code_props[prop].required:
                items.append(_build_item(endpoint, DriftCategory.REQUIRED_DRIFT, f"{location}.{prop}", f"Required flag differs for field '{prop}'", str(spec_props[prop].required), str(code_props[prop].required), "warning"))
            items.extend(_compare_schemas(endpoint, f"{location}.{prop}", spec_props[prop], code_props[prop]))
    elif spec_schema.type == "array":
        items.extend(_compare_schemas(endpoint, f"{location}[]", spec_schema.items, code_schema.items))
    return items


def _schema_summary(schema: FieldSchema) -> str:
    summary = schema.type
    if schema.format:
        summary = f"{summary}/{schema.format}"
    return summary


def _limitation(endpoint: str, location: str, reason: str) -> DriftItem:
    item = _build_item(endpoint, DriftCategory.ANALYSIS_LIMITATION, location, reason, None, None, "info")
    item.requires_review = True
    return item


def _build_item(
    endpoint: str,
    category: DriftCategory,
    location: str,
    detail: str,
    spec_evidence: str | None,
    code_evidence: str | None,
    severity: str,
) -> DriftItem:
    return DriftItem(
        id=make_drift_id(endpoint, location, category),
        endpoint=endpoint,
        category=category,
        location=location,
        detail=detail,
        spec_evidence=spec_evidence,
        code_evidence=code_evidence,
        severity=severity,
    )

