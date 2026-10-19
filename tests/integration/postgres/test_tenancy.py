"""Tenants against PostgreSQL: a user with several tenants chooses one after
logging in and gets tokens of that tenant, can switch to another, sees the
role and permissions of each membership, and the last-admin rule holds per
tenant. Tenants are provisioned idempotently from the CLI."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from config import config
from src.auth.infra.cookies import REFRESH_COOKIE
from src.tenancy import provision
from tests.integration.postgres.api import Api
from tests.integration.postgres.tenants import (
    DEFAULT_TENANT_RUC,
    OTHER_TENANT_RUC,
    ensure_tenant,
)

PASSWORD = "secret-pass-1"


def _device(client) -> TestClient:
    """A browser of its own: a separate cookie jar."""
    return TestClient(client.app)


def _login(client, username: str = "contador", password: str = PASSWORD):
    return _device(client).post(
        "/api/auth/login", json={"username": username, "password": password}
    )


def _select(client, token: str, tenant_id: str):
    return _device(client).post(
        "/api/auth/select-tenant",
        json={"tenantId": tenant_id},
        headers={"Authorization": f"Bearer {token}"},
    )


def _claims(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


def _error_code(response) -> str:
    return response.json()["errors"][0]["code"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _provision(monkeypatch, ruc: str, username: str, legal_name: str = "") -> int:
    monkeypatch.setenv("PROVISION_ADMIN_PASSWORD", PASSWORD)
    return provision.main(
        [
            "--ruc",
            ruc,
            "--legal-name",
            legal_name or f"Empresa {ruc}",
            "--admin-username",
            username,
            "--admin-email",
            f"{username}@test.local",
        ]
    )


@pytest.fixture
def admin_api(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def two_tenants(client, admin_api, pg_engine, monkeypatch) -> dict[str, str]:
    """`contador` is a VIEWER of the default tenant (created by its admin) and
    the ADMIN of a second one (provisioned from the CLI)"""
    admin_api.post(
        "/api/admin/users",
        {
            "username": "contador",
            "email": "contador@test.local",
            "password": PASSWORD,
            "role": 4,
        },
    )
    assert _provision(monkeypatch, OTHER_TENANT_RUC, "contador") == 0
    return {
        "default": str(ensure_tenant(pg_engine)),
        "other": str(ensure_tenant(pg_engine, OTHER_TENANT_RUC)),
    }


def test_a_user_with_two_tenants_chooses_one_and_gets_its_tokens(client, two_tenants):
    login = _login(client)

    assert login.status_code == 200, login.text
    body = login.json()["data"]
    assert "accessToken" not in body
    assert REFRESH_COOKIE not in login.cookies  # no session yet
    assert {(t["ruc"], t["role"]) for t in body["tenants"]} == {
        (DEFAULT_TENANT_RUC, 4),
        (OTHER_TENANT_RUC, 1),
    }

    tokens = {}
    for name, tenant_id in two_tenants.items():
        response = _select(client, body["selectionToken"], tenant_id)
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["tenant"]["id"] == tenant_id
        assert response.cookies[REFRESH_COOKIE]
        tokens[name] = _claims(data["accessToken"])

    assert tokens["default"]["tid"] == two_tenants["default"]
    assert tokens["other"]["tid"] == two_tenants["other"]
    assert tokens["default"]["sid"] != tokens["other"]["sid"]
    assert (tokens["default"]["role"], tokens["other"]["role"]) == (4, 1)
    assert "user:manage" in tokens["other"]["perms"]
    assert "user:manage" not in tokens["default"]["perms"]


def test_me_shows_the_tenant_and_the_permissions_of_that_membership(
    client, two_tenants
):
    selection = _login(client).json()["data"]["selectionToken"]
    viewer = _select(client, selection, two_tenants["default"]).json()["data"]

    me = client.get("/api/auth/me", headers=_bearer(viewer["accessToken"]))

    assert me.status_code == 200, me.text
    data = me.json()["data"]
    assert data["tenant"]["id"] == two_tenants["default"]
    assert data["role"] == 4
    assert "user:manage" not in data["permissions"]
    assert {t["id"] for t in data["tenants"]} == set(two_tenants.values())
    # The membership's role decides what the user can do here
    users = client.get("/api/admin/users", headers=_bearer(viewer["accessToken"]))
    assert users.status_code == 403


def test_switching_tenants_closes_the_current_session(client, two_tenants):
    selection = _login(client).json()["data"]["selectionToken"]
    browser = _device(client)
    first = browser.post(
        "/api/auth/select-tenant",
        json={"tenantId": two_tenants["default"]},
        headers=_bearer(selection),
    )
    old_cookie = browser.cookies[REFRESH_COOKIE]

    switched = browser.post(
        "/api/auth/select-tenant",
        json={"tenantId": two_tenants["other"]},
        headers=_bearer(first.json()["data"]["accessToken"]),
    )

    assert switched.status_code == 200, switched.text
    assert (
        _claims(switched.json()["data"]["accessToken"])["tid"] == two_tenants["other"]
    )
    assert browser.cookies[REFRESH_COOKIE] != old_cookie
    old = _device(client).post(
        "/api/auth/refresh", headers={"Cookie": f"{REFRESH_COOKIE}={old_cookie}"}
    )
    assert old.status_code == 401
    refreshed = browser.post("/api/auth/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["data"]["tenant"]["id"] == two_tenants["other"]


def test_a_tenant_without_membership_is_denied(client, admin_api, pg_engine):
    admin_api.post(
        "/api/admin/users",
        {"username": "caja1", "email": "c1@test.local", "password": PASSWORD},
    )
    stranger = str(ensure_tenant(pg_engine, OTHER_TENANT_RUC))
    login = _login(client, "caja1").json()["data"]

    response = _select(client, login["accessToken"], stranger)

    assert response.status_code == 403
    assert _error_code(response) == "TENANT_ACCESS_DENIED"


def test_a_user_without_an_active_membership_cannot_log_in(client, admin_api):
    created = admin_api.post(
        "/api/admin/users",
        {"username": "caja1", "email": "c1@test.local", "password": PASSWORD},
    )
    assert _login(client, "caja1").status_code == 200

    admin_api.post(f"/api/admin/users/{created['id']}/deactivate")
    response = _login(client, "caja1")

    assert response.status_code == 403
    assert _error_code(response) == "NO_ACTIVE_TENANT"


def test_a_suspended_tenant_is_not_offered(client, two_tenants, pg_engine):
    with pg_engine.begin() as conn:
        conn.execute(
            text("UPDATE tenants SET status = 'suspended' WHERE ruc = :ruc"),
            {"ruc": OTHER_TENANT_RUC},
        )

    login = _login(client).json()["data"]

    # Only one tenant left: straight into it
    assert login["tenant"]["id"] == two_tenants["default"]
    assert _claims(login["accessToken"])["tid"] == two_tenants["default"]


def test_admins_only_see_and_manage_the_users_of_their_tenant(
    client, admin_api, auth_headers, pg_engine
):
    other = ensure_tenant(pg_engine, OTHER_TENANT_RUC)
    other_admin = Api(client, auth_headers(tenant_id=other, username="admin-b"))
    stranger = other_admin.post(
        "/api/admin/users",
        {"username": "caja-b", "email": "cb@test.local", "password": PASSWORD},
    )

    assert [u["username"] for u in admin_api.get("/api/admin/users")] == ["admin-test"]
    admin_api.error("GET", f"/api/admin/users/{stranger['id']}", 404)
    admin_api.error("POST", f"/api/admin/users/{stranger['id']}/deactivate", 404)


def test_the_last_admin_rule_holds_per_tenant(
    client, admin_api, auth_headers, pg_engine
):
    other = ensure_tenant(pg_engine, OTHER_TENANT_RUC)
    admin_b = Api(client, auth_headers(tenant_id=other, username="admin-b"))
    second_b = admin_b.post(
        "/api/admin/users",
        {
            "username": "admin-b2",
            "email": "b2@test.local",
            "password": PASSWORD,
            "role": 1,
        },
    )
    [me] = admin_api.get("/api/admin/users")

    # The only admin of the default tenant stays...
    blocked = admin_api.error("POST", f"/api/admin/users/{me['id']}/deactivate", 409)
    assert blocked["code"] == "LAST_ADMIN"
    # ...while the other tenant, with two, can lose one, but not the last
    demoted = admin_b.put(f"/api/admin/users/{second_b['id']}/role", {"role": 2})
    assert demoted["role"] == 2
    [first_b] = [u for u in admin_b.get("/api/admin/users") if u["role"] == 1]
    last = admin_b.error("POST", f"/api/admin/users/{first_b['id']}/deactivate", 409)
    assert last["code"] == "LAST_ADMIN"


def test_the_password_of_a_user_in_another_tenant_cannot_be_reset_here(
    client, admin_api, two_tenants
):
    [contador] = [
        u for u in admin_api.get("/api/admin/users") if u["username"] == "contador"
    ]

    reset = admin_api.error(
        "POST",
        f"/api/admin/users/{contador['id']}/reset-password",
        409,
        json={"newPassword": "temporary-pass"},
    )
    rename = admin_api.error(
        "PUT",
        f"/api/admin/users/{contador['id']}/profile",
        409,
        json={"fullName": "Otro"},
    )

    assert reset["code"] == rename["code"] == "USER_IN_OTHER_TENANTS"
    # Their password still works
    assert _login(client).status_code == 200


def test_a_token_without_tenant_must_log_in_again(client, admin):
    now = datetime.now(UTC)
    legacy = jwt.encode(
        {
            "sub": "1",
            "username": "admin-test",
            "role": 1,
            "typ": "access",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "iss": config.JWT_ISSUER,
        },
        config.JWT_SECRET,
        algorithm="HS256",
    )

    response = client.get("/api/auth/me", headers=_bearer(legacy))

    assert response.status_code == 401
    assert _error_code(response) == "TENANT_REQUIRED"


def test_provisioning_leaves_the_tenant_ready_to_operate(
    client, monkeypatch, pg_engine
):
    for _ in range(2):
        assert _provision(monkeypatch, OTHER_TENANT_RUC, "duena") == 0

    token = _login(client, "duena").json()["data"]["accessToken"]
    api = Api(client, _bearer(token))
    [branch] = api.get("/api/admin/branches")
    [point] = api.get("/api/admin/emission-points")
    [warehouse] = api.get("/api/admin/warehouses")
    [location] = api.get("/api/admin/locations")
    [terminal] = api.get("/api/admin/pos-terminals")
    assert (branch["establishmentCode"], branch["isMain"]) == ("001", True)
    assert (point["branchId"], point["code"]) == (branch["id"], "001")
    assert (warehouse["branchId"], warehouse["isDefault"]) == (branch["id"], True)
    assert location["warehouseId"] == warehouse["id"]
    assert terminal["branchId"] == branch["id"]
    assert terminal["emissionPointId"] == point["id"]
    assert terminal["defaultLocationId"] == location["id"]
    # The POS of that branch finds its terminal
    branch_headers = {**_bearer(token), "X-Branch-Id": str(branch["id"])}
    terminals = Api(client, branch_headers).get("/api/pos/terminals")
    assert [t["code"] for t in terminals] == ["CAJA-01"]
    error = api.error("DELETE", f"/api/admin/branches/{branch['id']}", 409)
    assert error["code"] == "MAIN_BRANCH_DELETION"
    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT (SELECT count(*) FROM branches),"
                " (SELECT count(*) FROM emission_points),"
                " (SELECT count(*) FROM warehouses),"
                " (SELECT count(*) FROM locations),"
                " (SELECT count(*) FROM pos_terminals)"
            )
        ).one()
    assert tuple(rows) == (1, 1, 1, 1, 1)


def test_provisioning_twice_leaves_one_tenant_one_admin(client, monkeypatch, pg_engine):
    for _ in range(2):
        assert (
            _provision(monkeypatch, OTHER_TENANT_RUC, "duena", "Ferretería S.A.") == 0
        )

    with pg_engine.connect() as conn:
        counts = conn.execute(
            text(
                "SELECT (SELECT count(*) FROM tenants),"
                " (SELECT count(*) FROM users),"
                " (SELECT count(*) FROM memberships WHERE role = 1 AND active)"
            )
        ).one()
    assert tuple(counts) == (1, 1, 1)
    login = _login(client, "duena")
    assert login.status_code == 200, login.text
    assert login.json()["data"]["tenant"]["legalName"] == "Ferretería S.A."
    assert _claims(login.json()["data"]["accessToken"])["role"] == 1
