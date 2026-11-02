import json
import textwrap
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest
from typer.testing import CliRunner

from drift_agent.cli import _apply_ignore_rules, _build_output, app
from drift_agent.code_analyzer import analyze_codebase
from drift_agent.diff_engine import compute_drift
from drift_agent.types import (
    AgentFinding, DriftCategory, DriftTaxonomy, EndpointContract, FieldSchema,
    NormalizedContract, ParameterSchema, RequestBodySchema, ResponseSchema,
)
from drift_agent.spec_parser import parse_spec


def contract(endpoint, source="spec"):
    return NormalizedContract({"POST /items": endpoint}, source, {})


def endpoint(**kwargs):
    return EndpointContract("POST", "/items", **kwargs)


def test_every_taxonomy_group_is_emitted_and_priorities_are_sorted():
    spec = endpoint(
        description="Old description",
        parameters=[ParameterSchema("id", origin, True, FieldSchema("id", "string"))
                    for origin in ("path", "query", "header", "cookie")],
        request_body=RequestBodySchema(True, "application/json", FieldSchema("body", "object", properties={
            "value": FieldSchema("value", "string", required=True, description="Old", examples=["old"]),
            "unknown": FieldSchema("unknown", "unknown"),
        })),
        responses={"201": ResponseSchema("201", "application/json", None)},
    )
    code = endpoint(
        description="New description",
        request_body=RequestBodySchema(True, "application/json", FieldSchema("body", "object", properties={
            "value": FieldSchema("value", "integer", nullable=True, description="New", examples=[1]),
            "unknown": FieldSchema("unknown", "string"),
        })),
        responses={"202": ResponseSchema("202", "application/json", None)},
    )
    spec_contract, code_contract = contract(spec), contract(code, "code")
    spec_contract.endpoints["GET /missing"] = EndpointContract("GET", "/missing")
    code_contract.endpoints["GET /extra"] = EndpointContract("GET", "/extra")
    items = compute_drift(spec_contract, code_contract)
    assert {item.taxonomy for item in items} == set(DriftTaxonomy)
    assert [item.priority for item in items] == sorted(item.priority for item in items)
    assert {item.severity: item.priority for item in items} == {"error": "P1", "warning": "P2", "info": "P3"}
    assert len({item.id for item in items}) == len(items)
    parameters = [item for item in items if item.category == DriftCategory.PARAMETER_DRIFT]
    assert {item.location for item in parameters} == {f"parameters.{origin}.id" for origin in ("path", "query", "header", "cookie")}
    assert [item.to_dict() for item in items] == [item.to_dict() for item in compute_drift(spec_contract, code_contract)]
    schema = json.loads((Path(__file__).parents[2] / "docs/static-findings.schema.json").read_text(encoding="utf-8"))
    for item in items:
        jsonschema.validate(item.to_dict(), schema)


@pytest.mark.parametrize("origin", ["path", "query", "header"])
def test_schema_required_nullable_drift_retains_parameter_origin(origin):
    spec = endpoint(parameters=[ParameterSchema("value", origin, True, FieldSchema("value", "string"))])
    code = endpoint(parameters=[ParameterSchema("value", origin, False, FieldSchema("value", "string", nullable=True, format="uuid"))])
    items = compute_drift(contract(spec), contract(code))
    assert {item.taxonomy.value for item in items} == {"schema", "required_nullable"}
    assert all(item.parameter_location == origin for item in items)


@pytest.mark.parametrize("spec_examples,code_examples,equal", [
    (None, None, True), (None, [None], False), ([False], [0], False),
    ([{"a": 1, "b": 2}], [{"b": 2, "a": 1}], True), (["a"], ["b"], False),
])
def test_examples_compare_json_values(spec_examples, code_examples, equal):
    def with_examples(examples):
        return endpoint(request_body=RequestBodySchema(True, "application/json", FieldSchema("body", "string", examples=examples)))
    items = compute_drift(contract(with_examples(spec_examples)), contract(with_examples(code_examples)))
    assert bool(items) is not equal
    if items:
        assert items[0].category == DriftCategory.EXAMPLE_DRIFT
        assert items[0].priority == "P3"


def test_description_whitespace_and_missing_values():
    assert compute_drift(contract(endpoint(description="Some\n text")), contract(endpoint(description="Some text"))) == []
    items = compute_drift(contract(endpoint(description="Documented")), contract(endpoint()))
    assert len(items) == 1 and items[0].taxonomy == DriftTaxonomy.DESCRIPTION
    assert items[0].spec_evidence == '"Documented"' and items[0].code_evidence is None


def documented_pair(tmp_path):
    source = tmp_path / "app.py"
    source.write_text(textwrap.dedent('''
        from typing import Annotated
        from fastapi import FastAPI, Body, Query
        from pydantic import BaseModel, Field, ConfigDict
        app = FastAPI()
        class Payload(BaseModel):
            model_config = ConfigDict(json_schema_extra={"examples": [{"name": "Ada"}]})
            name: str = Field(description="Name", examples=["Ada"])
        @app.post("/items", summary="Create", description="Create an item", response_description="Saved")
        def create(q: Annotated[str, Query(description="Search", examples=["a"])],
                   body: Annotated[Payload, Body(openapi_examples={"demo": {"value": {"name": "Ada"}}})]) -> Payload:
            return body
    '''), encoding="utf-8")
    schema = {"type": "object", "required": ["name"], "examples": [{"name": "Ada"}],
              "properties": {"name": {"type": "string", "description": "Name", "examples": ["Ada"]}}}
    operation = {
        "summary": "Create", "description": "Create an item",
        "parameters": [{"name": "q", "in": "query", "required": True, "schema": {"type": "string"},
                        "description": "Search", "examples": {"search": {"value": "a"}}}],
        "requestBody": {"required": True, "content": {"application/json": {"schema": schema,
                        "examples": {"demo": {"value": {"name": "Ada"}}}}}},
        "responses": {"200": {"description": "Saved", "content": {"application/json": {"schema": deepcopy(schema)}}}},
    }
    spec_path = tmp_path / "openapi.json"
    document = {"openapi": "3.1.0", "info": {"title": "Metadata", "version": "1"},
                "paths": {"/items": {"post": operation}}}
    spec_path.write_text(json.dumps(document), encoding="utf-8")
    return source, spec_path, document


def test_metadata_round_trip_from_ast_and_openapi(tmp_path):
    source, spec_path, _ = documented_pair(tmp_path)
    spec, code = parse_spec(spec_path), analyze_codebase(source)
    assert compute_drift(spec, code) == []
    assert code.endpoints["POST /items"].request_body.schema.examples == [{"name": "Ada"}]
    # Changing documentation is detected at operation, parameter, schema and media levels.
    changed = spec.endpoints["POST /items"]
    changed.summary = "Changed"
    changed.description = "Changed"
    changed.parameters[0].description = "Changed"
    changed.request_body.examples = [{"name": "Grace"}]
    changed.request_body.schema.properties["name"].examples = ["Grace"]
    changed.responses["200"].description = "Changed"
    items = compute_drift(spec, code)
    assert {item.location for item in items} == {
        "endpoint.summary", "endpoint.description", "parameters.q.description", "request_body.examples",
        "request_body.schema.name.examples", "response.200.description",
    }
    assert all(item.priority == "P3" for item in items)


def test_computed_metadata_and_external_examples_require_review(tmp_path):
    source, spec_path, document = documented_pair(tmp_path)
    source.write_text(source.read_text(encoding="utf-8").replace('description="Search"', 'description=get_description()'), encoding="utf-8")
    document["paths"]["/items"]["post"]["requestBody"]["content"]["application/json"]["examples"] = {
        "remote": {"externalValue": "https://example.com/payload.json"}}
    spec_path.write_text(json.dumps(document), encoding="utf-8")
    items = compute_drift(parse_spec(spec_path), analyze_codebase(source))
    assert len(items) == 2
    assert all(item.requires_review and item.taxonomy == DriftTaxonomy.ANALYSIS_LIMITATION for item in items)


def test_parameter_schema_metadata_does_not_duplicate_parameter_documentation(tmp_path):
    source, spec_path, document = documented_pair(tmp_path)
    parameter = document["paths"]["/items"]["post"]["parameters"][0]
    parameter["schema"].update(description="Search", examples=["a"])
    del parameter["examples"]
    spec_path.write_text(json.dumps(document), encoding="utf-8")
    assert compute_drift(parse_spec(spec_path), analyze_codebase(source)) == []


def test_body_schema_and_media_examples_are_preserved_separately(tmp_path):
    source, spec_path, _ = documented_pair(tmp_path)
    source.write_text(source.read_text(encoding="utf-8").replace(
        'Body(openapi_examples=', 'Body(examples=[{"name": "Ada"}], openapi_examples='), encoding="utf-8")
    assert compute_drift(parse_spec(spec_path), analyze_codebase(source)) == []
    source.write_text(source.read_text(encoding="utf-8").replace(
        'openapi_examples={"demo": {"value": {"name": "Ada"}}}', 'openapi_examples=load_examples()'), encoding="utf-8")
    items = compute_drift(parse_spec(spec_path), analyze_codebase(source))
    assert len(items) == 1 and items[0].location == "request_body.examples" and items[0].requires_review


def test_outer_union_documentation_survives_normalization(tmp_path):
    source, spec_path, document = documented_pair(tmp_path)
    field = document["paths"]["/items"]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]["name"]
    field.pop("type")
    field["anyOf"] = [{"type": "string", "description": "Inner"}, {"type": "null"}]
    spec_path.write_text(json.dumps(document), encoding="utf-8")
    normalized = parse_spec(spec_path).endpoints["POST /items"].request_body.schema.properties["name"]
    assert normalized.description == "Name" and normalized.examples == ["Ada"] and normalized.nullable


def test_serialization_summaries_ignore_rules_and_schema(tmp_path):
    spec, code = contract(endpoint(description="Old")), contract(endpoint(description="New"))
    items = compute_drift(spec, code)
    finding = AgentFinding(items[0], "AMBIGUOUS", "low", "Review", [], None)
    assert finding.to_dict()["drift_item"] == items[0].to_dict()
    payload = _build_output("spec", "src", spec, code, items, [finding], None)
    assert payload["taxonomy_summary"] == {"description": 1}
    assert payload["priority_summary"] == {"P1": 0, "P2": 0, "P3": 1}
    assert _apply_ignore_rules(items, [{"taxonomy": "description"}]) == []
    assert _apply_ignore_rules(items, [{"category": "description_drift"}]) == []
    schema = json.loads((Path(__file__).parents[2] / "docs/static-findings.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(payload["items"][0], schema)
    json.dumps(payload)


def test_cli_exports_taxonomy_and_keeps_documentation_informational(tmp_path):
    source, spec_path, document = documented_pair(tmp_path)
    document["paths"]["/items"]["post"]["description"] = "Changed"
    spec_path.write_text(json.dumps(document), encoding="utf-8")
    result = CliRunner().invoke(app, ["--spec", str(spec_path), "--src", str(source), "--output-format", "json", "--exit-code"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["items"][0]["taxonomy"] == "description"
    assert payload["items"][0]["priority"] == "P3"
    assert payload["summary"] == {"error": 0, "warning": 0, "info": 1, "total": 1}
