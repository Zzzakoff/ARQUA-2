"""Parameter, schema and uncertainty regressions for task 1."""

import json
from pathlib import Path
from textwrap import dedent

import pytest
import jsonschema

from drift_agent.agent.core import DriftAgent
from drift_agent.code_analyzer import analyze_codebase
from drift_agent.diff_engine import compute_drift
from drift_agent.spec_parser import parse_spec
from drift_agent.types import DriftCategory, EndpointContract, FieldSchema, NormalizedContract, ParameterSchema, RequestBodySchema, ResponseSchema


def analyze(tmp_path, source):
    path = tmp_path / "app.py"
    path.write_text(dedent(source), encoding="utf-8")
    return analyze_codebase(path)


@pytest.mark.parametrize("declaration,required,nullable", [
    ("q: str", True, False),
    ("q: str | None", True, True),
    ("q: str | None = None", False, True),
    ("q: Optional[str] = Query(default=None)", False, True),
    ("q: str = Query()", True, False),
    ("q: str = Query(...)", True, False),
    ("q: str = Query(default='hello')", False, False),
    ("q: Annotated[str, Query(alias='search')]", True, False),
    ("q: Annotated[str | None, Query(alias='search')] = None", False, True),
    ("q: str = Query(default_factory=str)", False, False),
])
def test_parameter_required_is_independent_of_nullable(tmp_path, declaration, required, nullable):
    contract = analyze(tmp_path, f'''
        from typing import Annotated, Optional
        from fastapi import FastAPI, Query
        app = FastAPI()
        @app.get("/items")
        async def items({declaration}) -> str:
            return "ok"
    ''')
    param = contract.endpoints["GET /items"].parameters[0]
    assert param.name == ("search" if "alias=" in declaration else "q")
    assert param.required is required
    assert param.schema.required is required
    assert param.schema.nullable is nullable
    assert param.schema.type == "string"


@pytest.mark.parametrize("declaration,name,location,required", [
    ("q: str = Header(alias='X-Token')", "X-Token", "header", True),
    ("q: Annotated[str, Header(alias='X-Token')]", "X-Token", "header", True),
    ("x_token: str = Header(convert_underscores=False)", "x_token", "header", True),
    ("session: str = Cookie(default=None, alias='sid')", "sid", "cookie", False),
    ("user_id: Annotated[int, Path(alias='id')]", "id", "path", True),
])
def test_parameter_aliases(tmp_path, declaration, name, location, required):
    contract = analyze(tmp_path, f'''
        from typing import Annotated
        from fastapi import FastAPI, Header, Cookie, Path
        app = FastAPI()
        @app.get("/items/{{id}}")
        def items({declaration}) -> str:
            return "ok"
    ''')
    param = contract.endpoints["GET /items/{id}"].parameters[0]
    assert (param.name, param.location, param.required) == (name, location, required)


@pytest.mark.parametrize("declaration,required", [
    ("value: str", True), ("value: str = ...", True),
    ("value: str = Field(...)", True), ("value: str = Field()", True),
    ("value: str = Field('hello')", False),
    ("value: str = Field(default='hello')", False),
    ("value: str = Field(default_factory=str)", False),
    ("value: Annotated[str, Field(alias='value')] = 'hello'", False),
    ("value: Annotated[str, Field(default='hello')]", False),
])
def test_pydantic_defaults(tmp_path, declaration, required):
    contract = analyze(tmp_path, f'''
        from typing import Annotated
        from fastapi import FastAPI
        from pydantic import BaseModel, Field
        app = FastAPI()
        class Model(BaseModel):
            {declaration}
        @app.get("/items", response_model=Model)
        def items():
            pass
    ''')
    field = contract.endpoints["GET /items"].responses["200"].schema.properties["value"]
    assert field.type == "string"
    assert field.required is required


def test_annotated_body_embedding_and_field_alias(tmp_path):
    contract = analyze(tmp_path, '''
        from typing import Annotated
        from fastapi import FastAPI, Body
        from pydantic import BaseModel, Field
        app = FastAPI()
        class Model(BaseModel):
            name: Annotated[str | None, Field(alias="displayName", description="Manual text")]
        @app.post("/items")
        async def items(body: Annotated[Model, Body(embed=True, alias="payload")]) -> str:
            return "ok"
    ''')
    body = contract.endpoints["POST /items"].request_body
    assert body.required
    payload = body.schema.properties["payload"]
    assert payload.required
    field = payload.properties["displayName"]
    assert field.required and field.nullable
    assert field.description == "Manual text"
    assert "200" in contract.endpoints["POST /items"].responses


def test_recursive_models_stop_at_review_marker(tmp_path):
    contract = analyze(tmp_path, '''
        from fastapi import FastAPI
        from pydantic import BaseModel
        app = FastAPI()
        class Node(BaseModel):
            child: "Node | None" = None
        @app.get("/node", response_model=Node)
        def node():
            pass
    ''')
    child = contract.endpoints["GET /node"].responses["200"].schema.properties["child"]
    assert child.nullable and not child.required
    assert "Recursive" in child.analysis_note


def contract_pair(spec_endpoint, code_endpoint):
    return (NormalizedContract({"GET /items": spec_endpoint}, "spec", {}),
            NormalizedContract({"GET /items": code_endpoint}, "code", {}))


def test_required_differences_and_header_case():
    spec = EndpointContract("GET", "/items", parameters=[ParameterSchema("x-token", "header", True, FieldSchema("x", "string"))], request_body=RequestBodySchema(True, "application/json", FieldSchema("b", "string")))
    code = EndpointContract("GET", "/items", parameters=[ParameterSchema("X-Token", "header", False, FieldSchema("x", "string"))], request_body=RequestBodySchema(False, "application/json", FieldSchema("b", "string")), source_file="app.py", source_line=10)
    items = compute_drift(*contract_pair(spec, code))
    assert {item.location for item in items} == {"parameters.x-token.required", "request_body.required"}
    assert all(item.category == DriftCategory.REQUIRED_DRIFT for item in items)
    for item in items:
        data = item.to_dict()
        assert data["source_kind"] == "static"
        assert data["schema_version"] == "1.1"
        assert data["source_file"] == "app.py" and data["source_line"] == 10
        assert not data["requires_review"]
        json.dumps(data)
    assert [i.id for i in items] == [i.id for i in compute_drift(*contract_pair(spec, code))]


@pytest.mark.parametrize("schema", [FieldSchema("value", "unknown"), FieldSchema("value", "object", analysis_note="Unresolved model")])
def test_unknown_schema_is_not_a_type_or_missing_field_error(schema):
    spec = EndpointContract("GET", "/items", responses={"200": ResponseSchema("200", "application/json", FieldSchema("value", "string"))})
    code = EndpointContract("GET", "/items", responses={"200": ResponseSchema("200", "application/json", schema)})
    items = compute_drift(*contract_pair(spec, code))
    assert len(items) == 1
    assert items[0].category == DriftCategory.ANALYSIS_LIMITATION
    assert items[0].requires_review and items[0].severity == "info"
    # No initialized client: attempting an LLM call here would fail the test.
    result = DriftAgent.__new__(DriftAgent).analyze(items)[0]
    assert result.source_of_truth == "AMBIGUOUS" and result.patch is None


def test_dynamic_routes_do_not_prove_missing_endpoint(tmp_path):
    code = analyze(tmp_path, '''
        from fastapi import FastAPI
        app = FastAPI()
        @app.get(compute_path())
        async def items() -> str:
            return "ok"
    ''')
    spec = NormalizedContract({"GET /items": EndpointContract("GET", "/items")}, "spec", {})
    items = compute_drift(spec, code)
    assert not code.metadata["analysis_complete"]
    assert all(item.category == DriftCategory.ANALYSIS_LIMITATION for item in items)
    assert any(item.source_file == "app.py" and item.source_line == 4 for item in items)
    assert any(item.endpoint == "GET /items" for item in items)


def test_annotated_dependency_is_not_query_parameter(tmp_path):
    code = analyze(tmp_path, '''
        from typing import Annotated
        from fastapi import FastAPI, Depends
        app = FastAPI()
        @app.get("/items")
        def items(db: Annotated[str, Depends(get_db)]) -> str:
            return "ok"
    ''')
    endpoint = code.endpoints["GET /items"]
    assert not endpoint.parameters
    assert "parameters" in endpoint.analysis_notes


@pytest.mark.parametrize("schema,expected_type,nullable,uncertain", [
    ({"type": ["string", "null"]}, "string", True, False),
    ({"type": "string", "nullable": True}, "string", True, False),
    ({"anyOf": [{"type": "string"}, {"type": "null"}]}, "string", True, False),
    ({"type": ["string", "integer"]}, "unknown", False, True),
    ({"oneOf": [{"type": "object", "properties": {"a": {"type": "string"}}}, {"type": "object", "properties": {"b": {"type": "integer"}}}]}, "unknown", False, True),
    ({"allOf": [{"type": "object", "properties": {"a": {"type": "string"}}}, {"type": "object", "properties": {"b": {"type": "integer"}}}]}, "object", False, False),
])
def test_openapi_schema_variants(tmp_path, schema, expected_type, nullable, uncertain):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({"openapi": "3.1.0", "info": {"title": "Test", "version": "1"}, "paths": {"/items": {"get": {"responses": {"200": {"description": "OK", "content": {"application/json": {"schema": schema}}}}}}}}), encoding="utf-8")
    field = parse_spec(path).endpoints["GET /items"].responses["200"].schema
    assert (field.type, field.nullable, bool(field.analysis_note)) == (expected_type, nullable, uncertain)
    if "allOf" in schema:
        assert set(field.properties) == {"a", "b"}


def test_unannotated_response_is_explicitly_uncertain(tmp_path):
    code = analyze(tmp_path, '''
        from fastapi import FastAPI
        app = FastAPI()
        @app.get("/items")
        def items():
            return load_items()
    ''')
    schema = code.endpoints["GET /items"].responses["200"].schema
    assert schema.type == "unknown" and schema.analysis_note


@pytest.mark.parametrize("annotation,expected_type", [("Literal[1, 2]", "integer"), ("Literal[True, False]", "boolean"), ("Literal['a', 'b']", "string")])
def test_literal_types(tmp_path, annotation, expected_type):
    code = analyze(tmp_path, f'''
        from typing import Literal
        from fastapi import FastAPI
        app = FastAPI()
        @app.get("/items")
        def items(q: {annotation}) -> str:
            return "ok"
    ''')
    assert code.endpoints["GET /items"].parameters[0].schema.type == expected_type


def test_router_cycle_is_reported_without_hanging(tmp_path):
    code = analyze(tmp_path, '''
        from fastapi import FastAPI, APIRouter
        app = FastAPI()
        router = APIRouter(prefix="/items")
        app.include_router(router)
        router.include_router(router, prefix="/loop")
        @router.get("")
        def items() -> str:
            return "ok"
    ''')
    assert not code.metadata["analysis_complete"]
    assert any("Cyclic" in item["message"] for item in code.metadata["diagnostics"])


def test_unattached_router_is_not_a_registered_endpoint(tmp_path):
    code = analyze(tmp_path, '''
        from fastapi import FastAPI, APIRouter
        app = FastAPI()
        unused = APIRouter()
        @unused.get("/unused")
        def unused_handler() -> str:
            return "ok"
    ''')
    assert not code.endpoints


def test_environment_directories_are_not_scanned(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "bad.py").write_text("not valid python!!!", encoding="utf-8")
    (tmp_path / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()", encoding="utf-8")
    assert not analyze_codebase(tmp_path).endpoints


def test_missing_spec_reference_is_a_review_item(tmp_path):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({"openapi": "3.0.3", "info": {"title": "Test", "version": "1"}, "paths": {"/items": {"get": {"responses": {"200": {"description": "OK", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Missing"}}}}}}}}}), encoding="utf-8")
    spec = parse_spec(path)
    code = NormalizedContract({"GET /items": EndpointContract("GET", "/items", responses={"200": ResponseSchema("200", "application/json", FieldSchema("result", "string"))})}, "code", {})
    items = compute_drift(spec, code)
    assert len(items) == 1 and items[0].requires_review
    assert "Reference target not found" in items[0].detail


def test_output_contract_matches_json_schema(tmp_path):
    from drift_agent.cli import _build_output
    spec = NormalizedContract({"GET /items": EndpointContract("GET", "/items")}, "spec", {})
    code = analyze(tmp_path, '''
        from fastapi import FastAPI
        app = FastAPI()
        app.add_api_route("/items", handler)
    ''')
    items = compute_drift(spec, code)
    schema = json.loads((Path(__file__).parents[2] / "docs" / "static-findings.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    payload = _build_output("spec.json", "app.py", spec, code, items, [], None)
    assert payload["summary"]["error"] == 0
    assert len({item.id for item in items}) == len(items)
    for item in payload["items"]:
        jsonschema.validate(item, schema)
    json.dumps(payload)


@pytest.mark.parametrize("declaration", ["response_model=None", "status_code=compute_status()", "responses={404: {'description': 'Missing'}}"])
def test_unsupported_response_configuration_is_not_guessed(tmp_path, declaration):
    code = analyze(tmp_path, f'''
        from fastapi import FastAPI
        app = FastAPI()
        @app.get("/items", {declaration})
        def items() -> str:
            return "ok"
    ''')
    spec_endpoint = EndpointContract("GET", "/items", responses={"200": ResponseSchema("200", "application/json", FieldSchema("result", "string"))})
    spec = NormalizedContract({"GET /items": spec_endpoint}, "spec", {})
    items = compute_drift(spec, code)
    assert len(items) == 1 and items[0].requires_review
