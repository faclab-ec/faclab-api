"""Integration clients end to end on PostgreSQL (S6.2): an admin creates a
client, the client gets a token at POST /api/oauth/token, the token is
rejected by the routes of the frontend and by another branch, revoking stops
it within the status cache, and the secret never reaches a response after its
creation nor any log."""

import base64
import logging
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from config import config
from src.auth.domain.entities import Role
from src.integrations.infra.access import integration_access
from tests.integration.postgres.api import Api, concurrently, make_branch
from tests.integration.postgres.tenants import OTHER_TENANT_RUC, ensure_tenant

TOKEN = "/api/oauth/token"
CLIENTS = "/api/admin/integrations"


@pytest.fixture
def api(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def branches(api) -> tuple[int, int]:
    return make_branch(api, "001")["id"], make_branch(api, "002")["id"]


def _create(api: Api, **body) -> dict:
    return api.post(
        CLIENTS,
        {"name": "Tienda web", "scopes": ["stock:read", "sales:write"], **body},
    )


def _basic(client_id: str, secret: str) -> dict[str, str]:
    raw = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


def _token(client: TestClient, created: dict, secret: str | None = None, **form):
    return client.post(
        TOKEN,
        data={"grant_type": "client_credentials", **form},
        headers=_basic(created["clientId"], secret or created["clientSecret"]),
    )


def _bearer(response) -> dict[str, str]:
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _code(response) -> tuple[int, str]:
    return response.status_code, response.json()["errors"][0]["code"]


def test_a_client_gets_a_token_with_its_tenant_scopes_and_branches(
    client, api, tenant, branches
):
    created = _create(api, branchIds=[branches[0]])

    response = _token(client, created)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == config.JWT_ACCESS_TTL_SECONDS
    assert body["scope"] == "sales:write stock:read"
    claims = jwt.decode(body["access_token"], options={"verify_signature": False})
    assert claims["tid"] == str(tenant)
    assert claims["azp"] == created["clientId"]
    assert claims["sub"] == f"client:{created['clientId']}"
    assert claims["scope"] == "sales:write stock:read"
    assert claims["bids"] == [branches[0]]
    assert claims["cred"] == created["secrets"][0]["id"]


def test_the_credentials_can_go_in_the_form(client, api):
    created = _create(api)

    response = client.post(
        TOKEN,
        data={
            "grant_type": "client_credentials",
            "client_id": created["clientId"],
            "client_secret": created["clientSecret"],
            "scope": "stock:read",
        },
    )

    assert response.status_code == 200
    assert response.json()["scope"] == "stock:read"


@pytest.mark.parametrize(
    ("form", "secret", "status", "error"),
    [
        ({"grant_type": "password"}, None, 400, "unsupported_grant_type"),
        ({}, None, 400, "invalid_request"),
        ({"grant_type": "client_credentials"}, "wrong", 401, "invalid_client"),
        (
            {"grant_type": "client_credentials", "scope": "products:write"},
            None,
            400,
            "invalid_scope",
        ),
    ],
)
def test_token_errors_follow_oauth(client, api, form, secret, status, error):
    created = _create(api)

    response = client.post(
        TOKEN,
        data=form,
        headers=_basic(created["clientId"], secret or created["clientSecret"]),
    )

    assert response.status_code == status
    assert response.json()["error"] == error
    if status == 401:
        assert response.headers["www-authenticate"].startswith("Basic")


def test_an_unknown_client_gets_no_token(client):
    response = _token(
        client, {"clientId": "fl_test_000000000000", "clientSecret": "nope"}
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


def test_a_client_of_one_company_with_the_secret_of_another_gets_no_token(
    client, api, auth_headers, pg_engine
):
    """The tenant comes from the client_id; the secret is looked up in it (S9.3)"""
    ours = _create(api)
    other_tenant = ensure_tenant(pg_engine, OTHER_TENANT_RUC)
    theirs = _create(
        Api(
            client,
            auth_headers(Role.ADMIN, tenant_id=other_tenant, username="other-admin"),
        )
    )

    response = _token(client, ours, secret=theirs["clientSecret"])

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"
    assert _token(client, theirs).status_code == 200


def test_the_routes_of_the_frontend_reject_an_integration(client, api):
    headers = _bearer(_token(client, _create(api)))

    assert _code(client.get("/api/admin/products", headers=headers)) == (
        403,
        "INTEGRATION_NOT_ALLOWED",
    )
    assert _code(client.post("/api/pos/sales", json={}, headers=headers)) == (
        403,
        "INTEGRATION_NOT_ALLOWED",
    )
    # Nor the user's own routes
    assert client.get("/api/auth/me", headers=headers).status_code == 403


def test_a_client_limited_to_a_branch_cant_enter_another(client, api, branches):
    headers = _bearer(_token(client, _create(api, branchIds=[branches[0]])))

    response = client.get(
        "/api/admin/products", headers={**headers, "X-Branch-Id": str(branches[1])}
    )

    assert _code(response) == (403, "BRANCH_ACCESS_DENIED")


def test_revoking_a_client_invalidates_its_tokens_within_a_minute(
    client, api, monkeypatch
):
    created = _create(api)
    headers = _bearer(_token(client, created))
    # Accepted as the integration (the route refuses it, not the token)
    assert _code(client.get("/api/admin/products", headers=headers))[1] == (
        "INTEGRATION_NOT_ALLOWED"
    )

    api.post(f"{CLIENTS}/{created['id']}/revoke")

    # No new token at once
    assert _token(client, created).json()["error"] == "invalid_client"
    # And the one it had is invalid once the status cache (<= 60 s) expires
    access = integration_access()
    monkeypatch.setattr(access, "_clock", lambda: time.monotonic() + 61)
    assert _code(client.get("/api/admin/products", headers=headers)) == (
        401,
        "INVALID_TOKEN",
    )


def test_rotation_keeps_the_integration_working(client, api):
    created = _create(api)
    old_headers = _bearer(_token(client, created))
    rotated = api.post(f"{CLIENTS}/{created['id']}/secrets", {})

    # Both secrets work until the old one is revoked
    new_headers = _bearer(_token(client, created, rotated["clientSecret"]))
    _bearer(_token(client, created))
    api.post(f"{CLIENTS}/{created['id']}/secrets/{created['secrets'][0]['id']}/revoke")

    assert _token(client, created).json()["error"] == "invalid_client"
    assert _code(client.get("/api/admin/products", headers=old_headers))[0] == 401
    assert _code(client.get("/api/admin/products", headers=new_headers))[0] == 403


def test_the_usage_of_each_day(client, api):
    created = _create(api)
    headers = _bearer(_token(client, created))
    _token(client, created, "wrong")
    client.get("/api/admin/products", headers=headers)

    [day] = api.get(f"{CLIENTS}/{created['id']}/usage")

    assert (day["tokenRequests"], day["tokenFailures"]) == (1, 1)
    assert (day["requests"], day["errors"]) == (1, 1)
    assert day["lastSeenAt"] is not None
    assert api.get(f"{CLIENTS}/{created['id']}")["lastUsedAt"] is not None


def test_the_secret_is_shown_only_once_and_never_logged(client, api, caplog):
    with caplog.at_level(logging.DEBUG):
        created = _create(api)
        rotated = api.post(f"{CLIENTS}/{created['id']}/secrets", {})
        _token(client, created)
        _token(client, created, "wrong-secret")
        client.post(
            TOKEN,
            data={
                "grant_type": "client_credentials",
                "client_id": created["clientId"],
                "client_secret": rotated["clientSecret"],
            },
        )
        detail = api.get(f"{CLIENTS}/{created['id']}")
        listing = api.get(CLIENTS)

    secrets = [created["clientSecret"], rotated["clientSecret"]]
    shown = f"{detail} {listing}"
    assert not any(secret in shown for secret in secrets)
    logged = [record.getMessage() for record in caplog.records]
    assert any("integration_token_issued" in line for line in logged)
    assert any("integration_token_denied" in line for line in logged)
    assert not any(secret in line for line in logged for secret in secrets)


def test_with_integrations_disabled_there_are_no_tokens(client, api, monkeypatch):
    created = _create(api)
    monkeypatch.setattr(config, "INTEGRATIONS_ENABLED", False)

    response = _token(client, created)

    assert response.status_code == 503
    assert response.json()["error"] == "temporarily_unavailable"


def test_asking_for_tokens_while_using_one_does_not_deadlock(client, api, branches):
    """Both write the client's usage of the day and its `last_used_at`: in
    opposite orders they deadlocked, and the token endpoint answered 500
    (found by the load tests of S9.2)."""
    created = _create(api)
    bearer = _bearer(_token(client, created))
    stock = f"/api/v1/stock?branchId={branches[0]}"

    for _ in range(5):
        responses = concurrently(
            *[lambda other: _token(other, created)] * 8,
            *[lambda other: other.get(stock, headers=bearer)] * 8,
        )

        assert [r.status_code for r in responses] == [200] * 16
