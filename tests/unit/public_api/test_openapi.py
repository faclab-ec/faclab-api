"""The public OpenAPI (S6.3) is the published contract: the snapshot in
docs/public-api is what the CI compares against the base branch."""

import pytest
from fastapi.routing import APIRoute

from main import app
from src.public_api.infra.openapi import SNAPSHOT, public_openapi, render


@pytest.fixture(scope="module")
def schema() -> dict:
    return public_openapi(app)


def test_the_snapshot_is_the_contract_of_the_code(schema):
    assert render(schema) == SNAPSHOT.read_text(), (
        "the public API changed: run `make public-openapi` and review the diff "
        "(the CI refuses an incompatible change)"
    )


def test_it_only_documents_the_public_routes(schema):
    assert set(schema["paths"]) == {
        route.path
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1")
    } | {"/api/oauth/token"}


def test_every_public_operation_declares_its_scopes(schema):
    for path, item in schema["paths"].items():
        if not path.startswith("/api/v1"):
            continue
        for method, operation in item.items():
            assert "clientCredentials" in operation["security"][0], (method, path)


def test_every_post_requires_an_idempotency_key(schema):
    for path, item in schema["paths"].items():
        if path.startswith("/api/v1") and "post" in item:
            headers = {
                p["name"]: p["required"]
                for p in item["post"].get("parameters", [])
                if p["in"] == "header"
            }
            assert headers.get("Idempotency-Key") is True, path


def test_money_and_quantities_are_strings(schema):
    sale = schema["components"]["schemas"]["Sale"]["properties"]
    item = schema["components"]["schemas"]["SaleItem"]["properties"]

    assert sale["total"]["type"] == "string"
    assert item["quantity"]["type"] == "string"
    assert item["unitPrice"]["type"] == "string"
