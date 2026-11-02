from pathlib import Path

from drift_agent.code_analyzer import analyze_codebase


FIXTURES = Path(__file__).parent / "fixtures" / "apps"


def test_analyze_simple_app():
    contract = analyze_codebase(FIXTURES / "simple_app")

    assert contract.source == "code"
    assert len(contract.endpoints) == 2
    get_endpoint = contract.endpoints["GET /users/{user_id}"]
    assert get_endpoint.source_file == "app.py"
    assert any(param.location == "path" and param.name == "user_id" for param in get_endpoint.parameters)
    assert any(param.location == "query" and param.name == "include_meta" for param in get_endpoint.parameters)
    assert any(param.location == "header" and param.name == "X-Trace-Id" for param in get_endpoint.parameters)
    assert get_endpoint.responses["200"].schema.properties["created_at"].format == "date-time"


def test_analyze_multi_file_app():
    contract = analyze_codebase(FIXTURES / "multi_file_app")

    assert "GET /api/users/{user_id}" in contract.endpoints
    endpoint = contract.endpoints["GET /api/users/{user_id}"]
    assert endpoint.tags == ["users"]
    assert endpoint.source_file.endswith("routers\\users.py") or endpoint.source_file.endswith("routers/users.py")

