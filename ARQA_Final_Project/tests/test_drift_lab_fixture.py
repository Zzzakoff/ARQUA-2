from pathlib import Path

from drift_agent.code_analyzer import analyze_codebase
from drift_agent.diff_engine import compute_drift
from drift_agent.spec_parser import parse_spec


ROOT = Path(__file__).parent
APP = ROOT / "fixtures" / "apps" / "drift_lab_app"
SPEC = ROOT / "fixtures" / "specs" / "drift_lab.yaml"


def test_drift_lab_app_exercises_static_fastapi_analysis():
    contract = analyze_codebase(APP)

    assert set(contract.endpoints) == {
        "GET /admin/audit",
        "GET /api/orders",
        "POST /api/orders",
        "DELETE /api/orders/{order_id}",
        "GET /api/users/{user_id}",
        "POST /api/users",
        "GET /health",
        "GET /internal/metrics",
    }
    user = contract.endpoints["GET /api/users/{user_id}"]
    assert user.responses["200"].schema.properties["id"].format == "uuid"
    assert any(param.location == "cookie" and param.name == "session_id" for param in user.parameters)
    create_user = contract.endpoints["POST /api/users"]
    assert "inviteCode" in create_user.request_body.schema.properties
    assert create_user.request_body.schema.properties["inviteCode"].nullable is True


def test_drift_lab_spec_and_app_produce_representative_drift_categories():
    spec_contract = parse_spec(SPEC)
    code_contract = analyze_codebase(APP)

    items = compute_drift(spec_contract, code_contract)
    categories = {item.category.value for item in items}

    assert "missing_endpoint" in categories
    assert "ghost_endpoint" in categories
    assert "parameter_drift" in categories
    assert "destructive_drift" in categories
    assert "additive_drift" in categories
    assert "type_drift" in categories
    assert "status_code_drift" in categories
    assert any(item.endpoint == "GET /reports/summary" for item in items)
    assert any(item.endpoint == "DELETE /api/orders/{order_id}" for item in items)
    assert any(item.location == "parameters.limit" and item.severity == "error" for item in items)
    assert any(item.location == "request_body.schema.inviteCode" for item in items)
