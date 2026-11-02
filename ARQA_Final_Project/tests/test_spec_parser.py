from pathlib import Path

from drift_agent.spec_parser import parse_spec


FIXTURES = Path(__file__).parent / "fixtures" / "specs"


def test_parse_simple_spec():
    contract = parse_spec(FIXTURES / "simple.yaml")

    assert contract.source == "spec"
    assert len(contract.endpoints) == 3
    endpoint = contract.endpoints["POST /users"]
    assert endpoint.request_body is not None
    assert endpoint.request_body.content_type == "application/json"
    assert endpoint.request_body.schema.properties["email"].format == "email"
    assert endpoint.responses["201"].schema.properties["id"].type == "integer"


def test_parse_refs_spec():
    contract = parse_spec(FIXTURES / "with_refs.yaml")

    response_schema = contract.endpoints["GET /users/{user_id}"].responses["200"].schema
    assert response_schema.properties["profile"].properties["email"].format == "email"


def test_parse_circular_ref_spec():
    contract = parse_spec(FIXTURES / "circular_refs.yaml")

    address_schema = contract.endpoints["GET /users/{user_id}"].responses["200"].schema.properties["address"]
    assert address_schema.type == "object"
    assert "circular ref" in address_schema.description
