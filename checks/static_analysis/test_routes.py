"""Route regression checks kept separate from the team's tests directory."""

import json
from textwrap import dedent

import pytest

from drift_agent.code_analyzer import analyze_codebase
from drift_agent.diff_engine import compute_drift
from drift_agent.spec_parser import parse_spec


def analyze(tmp_path, source):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text(dedent(source), encoding="utf-8")
    return analyze_codebase(app_dir)


@pytest.mark.parametrize("definition", ["def", "async def"])
@pytest.mark.parametrize("path_argument", ['"/users/{user_id}"', 'path="/users/{user_id}"'])
def test_handler_preserves_parameters_and_response(tmp_path, definition, path_argument):
    contract = analyze(tmp_path, f'''
        from fastapi import FastAPI, Query
        from pydantic import BaseModel
        app = FastAPI()
        class User(BaseModel):
            id: int
        @app.get({path_argument}, response_model=User, tags=["users"])
        {definition} user(user_id: int, limit: int = Query(10)):
            return {{"id": user_id}}
    ''')
    assert set(contract.endpoints) == {"GET /users/{user_id}"}
    endpoint = contract.endpoints["GET /users/{user_id}"]
    assert {(p.name, p.location, p.schema.type) for p in endpoint.parameters} == {
        ("user_id", "path", "integer"), ("limit", "query", "integer")
    }
    assert endpoint.responses["200"].schema.properties["id"].type == "integer"
    assert endpoint.tags == ["users"]
    assert endpoint.source_file == "main.py"
    assert endpoint.source_line == 7


@pytest.mark.parametrize("definition", ["def", "async def"])
@pytest.mark.parametrize("methods", ['["GET", "POST"]', '("get", "POST")', '{"POST", "GET"}'])
def test_api_route_multiple_methods(tmp_path, definition, methods):
    contract = analyze(tmp_path, f'''
        from fastapi import FastAPI
        app = FastAPI()
        @app.api_route(path="/items", methods={methods}, status_code=202)
        {definition} items() -> str:
            return "ok"
    ''')
    assert set(contract.endpoints) == {"GET /items", "POST /items"}
    assert list(contract.endpoints) == ["GET /items", "POST /items"]
    for endpoint in contract.endpoints.values():
        assert endpoint.responses["202"].schema.type == "string"


@pytest.mark.parametrize("methods_argument", ["", ", methods=None", ", methods=[]"])
def test_api_route_defaults_to_get(tmp_path, methods_argument):
    contract = analyze(tmp_path, f'''
        from fastapi import FastAPI
        app = FastAPI()
        @app.api_route("/health"{methods_argument})
        def health() -> str:
            return "ok"
    ''')
    assert set(contract.endpoints) == {"GET /health"}
    assert "200" in contract.endpoints["GET /health"].responses


@pytest.mark.parametrize("decorator", [
    '@app.get(dynamic_path)',
    '@app.api_route("/items", methods=dynamic_methods)',
    '@app.api_route("/items", methods=["GET", dynamic_method])',
    '@app.api_route("/items", methods="GET")',
])
def test_dynamic_declaration_is_not_guessed(tmp_path, caplog, decorator):
    contract = analyze(tmp_path, f'''
        from fastapi import FastAPI
        app = FastAPI()
        {decorator}
        async def items():
            return {{"ok": True}}
    ''')
    assert contract.endpoints == {}
    assert "Skipping" in caplog.text


def test_async_router_multiple_prefixes_and_stacked_decorators(tmp_path):
    (tmp_path / "main.py").write_text(dedent('''
        from fastapi import FastAPI
        from routes import router
        app = FastAPI()
        app.include_router(router, prefix="/v1")
        app.include_router(router, prefix="/v2")
    '''), encoding="utf-8")
    (tmp_path / "routes.py").write_text(dedent('''
        from fastapi import APIRouter
        router = APIRouter(prefix="/users", tags=["users"])
        @router.get(path="/{user_id}")
        @router.api_route("/{user_id}", methods=["PUT", "PATCH"], status_code=202)
        async def user(user_id: int) -> str:
            return "ok"
    '''), encoding="utf-8")
    contract = analyze_codebase(tmp_path)
    assert set(contract.endpoints) == {
        f"{method} /{version}/users/{{user_id}}"
        for version in ("v1", "v2") for method in ("GET", "PUT", "PATCH")
    }
    for endpoint in contract.endpoints.values():
        assert endpoint.tags == ["users"]
        assert endpoint.source_file == "routes.py"
        assert endpoint.parameters[0].name == "user_id"


def test_async_request_body_and_inferred_response(tmp_path):
    contract = analyze(tmp_path, '''
        from fastapi import FastAPI
        from pydantic import BaseModel
        app = FastAPI()
        class Payload(BaseModel):
            name: str
        @app.post(path="/items", status_code=201)
        async def create(body: Payload):
            return {"name": body.name}
    ''')
    endpoint = contract.endpoints["POST /items"]
    assert endpoint.request_body.schema.properties["name"].type == "string"
    assert "name" in endpoint.responses["201"].schema.properties


def test_async_routes_match_spec_without_false_missing_endpoints(tmp_path):
    contract = analyze(tmp_path, '''
        from fastapi import FastAPI
        app = FastAPI()
        @app.api_route(path="/health", methods=["GET", "POST"], status_code=200)
        async def health() -> str:
            return "ok"
    ''')
    response = {"200": {"description": "OK", "content": {
        "application/json": {"schema": {"type": "string"}}
    }}}
    spec_path = tmp_path / "openapi.json"
    spec_path.write_text(json.dumps({
        "openapi": "3.1.0", "info": {"title": "Routes", "version": "1"},
        "paths": {"/health": {method: {"responses": response} for method in ("get", "post")}},
    }), encoding="utf-8")
    assert compute_drift(parse_spec(spec_path), contract) == []
