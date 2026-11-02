from drift_agent.diff_engine import compute_drift
from drift_agent.types import EndpointContract, FieldSchema, NormalizedContract, ParameterSchema, ResponseSchema


def _contract(endpoints):
    return NormalizedContract(endpoints=endpoints, source="spec", metadata={})


def test_missing_endpoint():
    spec = _contract({"GET /users": EndpointContract(method="GET", path="/users")})
    code = _contract({})

    items = compute_drift(spec, code)

    assert len(items) == 1
    assert items[0].category.value == "missing_endpoint"


def test_additive_field():
    spec = _contract(
        {
            "GET /users": EndpointContract(
                method="GET",
                path="/users",
                responses={
                    "200": ResponseSchema(
                        status_code="200",
                        content_type="application/json",
                        schema=FieldSchema(
                            name="response",
                            type="object",
                            properties={"id": FieldSchema(name="id", type="integer", required=True)},
                        ),
                    )
                },
            )
        }
    )
    code = _contract(
        {
            "GET /users": EndpointContract(
                method="GET",
                path="/users",
                responses={
                    "200": ResponseSchema(
                        status_code="200",
                        content_type="application/json",
                        schema=FieldSchema(
                            name="response",
                            type="object",
                            properties={
                                "id": FieldSchema(name="id", type="integer", required=True),
                                "created_at": FieldSchema(name="created_at", type="string", format="date-time"),
                            },
                        ),
                    )
                },
            )
        }
    )

    items = compute_drift(spec, code)

    assert any(item.category.value == "additive_drift" and item.location.endswith("created_at") for item in items)


def test_422_ignored():
    spec = _contract(
        {
            "GET /users": EndpointContract(
                method="GET",
                path="/users",
                responses={"200": ResponseSchema(status_code="200", content_type="application/json", schema=None)},
            )
        }
    )
    code = _contract(
        {
            "GET /users": EndpointContract(
                method="GET",
                path="/users",
                responses={
                    "200": ResponseSchema(status_code="200", content_type="application/json", schema=None),
                    "422": ResponseSchema(status_code="422", content_type="application/json", schema=None),
                },
            )
        }
    )

    items = compute_drift(spec, code)

    assert items == []
