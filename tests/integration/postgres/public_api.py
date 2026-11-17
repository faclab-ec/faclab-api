"""Helpers of the public API's Postgres tests (S6.3): an integration client's
token, and the check that a response sends nothing its OpenAPI doesn't
document."""

import copy
import functools
import re
from typing import Any

from fastapi.testclient import TestClient
from httpx import Response
from jsonschema import Draft202012Validator

from main import app
from src.auth.domain.scopes import Scope
from src.public_api.infra.openapi import public_openapi
from src.public_api.infra.rate_limit import PublicApiRateLimitMiddleware
from tests.integration.postgres.api import Api

ALL_SCOPES = [scope.value for scope in Scope]


def integration_headers(
    api: Api,
    client: TestClient,
    scopes: list[str] | None = None,
    branch_ids: list[int] | None = None,
    name: str = "Tienda web",
) -> dict[str, str]:
    """Bearer headers of a new integration client of the admin's tenant"""
    body: dict[str, Any] = {"name": name, "scopes": scopes or ALL_SCOPES}
    if branch_ids is not None:
        body["branchIds"] = branch_ids
    created = api.post("/api/admin/integrations", body)
    response = client.post(
        "/api/oauth/token",
        data={"grant_type": "client_credentials"},
        auth=(created["clientId"], created["clientSecret"]),
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@functools.cache
def _document() -> dict:
    """The public OpenAPI with every object closed: a field the schema doesn't
    list fails the validation"""
    document = copy.deepcopy(public_openapi(app))
    for schema in document["components"]["schemas"].values():
        _close(schema)
    return document


def _close(schema: Any) -> None:
    if isinstance(schema, dict):
        if schema.get("type") == "object" and "properties" in schema:
            schema["additionalProperties"] = False
        for value in schema.values():
            _close(value)
    elif isinstance(schema, list):
        for value in schema:
            _close(value)


def _operation(method: str, path: str) -> dict:
    for template, item in _document()["paths"].items():
        pattern = "^" + re.sub(r"\{[^}]+\}", r"[^/]+", template) + "$"
        if re.match(pattern, path) and method.lower() in item:
            return item[method.lower()]
    raise AssertionError(f"{method} {path} is not in the public OpenAPI")


def assert_documented(response: Response) -> Any:
    """The response's body matches the schema its operation documents for its
    status, with no field more; returns its `data`"""
    request = response.request
    operation = _operation(request.method, request.url.path)
    documented = operation["responses"].get(str(response.status_code))
    assert documented is not None, (
        f"{request.method} {request.url.path} doesn't document {response.status_code}"
    )
    schema = documented["content"]["application/json"]["schema"]
    body = response.json()
    validator = Draft202012Validator(
        {**schema, "components": _document()["components"]}
    )
    errors = [
        f"{'/'.join(map(str, e.absolute_path))}: {e.message}"
        for e in validator.iter_errors(body)
    ]
    assert not errors, "\n".join(errors)
    return body.get("data")


def rate_limit_middleware(client: TestClient) -> PublicApiRateLimitMiddleware:
    """The app's instance (its stack is built on the first request)"""
    client.get("/health/live")
    layer = app.middleware_stack
    while layer is not None and not isinstance(layer, PublicApiRateLimitMiddleware):
        layer = getattr(layer, "app", None)
    assert layer is not None, "the rate limit middleware isn't mounted"
    return layer
