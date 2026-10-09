"""Sessions against PostgreSQL: refresh tokens stop working after logout, a
password change or deactivation, and the last admin can't be removed."""

import jwt
import pytest

from tests.integration.postgres.api import Api

PASSWORD = "secret-pass-1"


@pytest.fixture
def admin_api(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def cashier(admin_api) -> dict:
    return admin_api.post(
        "/api/admin/users",
        {
            "username": "caja1",
            "email": "caja1@test.local",
            "password": PASSWORD,
            "role": 5,
        },
    )


def _login(client, password: str = PASSWORD) -> dict:
    response = client.post(
        "/api/auth/login", json={"username": "caja1", "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _refresh(client, tokens: dict):
    return client.post(
        "/api/auth/refresh", json={"refreshToken": tokens["refreshToken"]}
    )


def _error_code(response) -> str:
    return response.json()["errors"][0]["code"]


def test_logout_ends_the_session(client, cashier):
    tokens = _login(client)
    assert _refresh(client, tokens).status_code == 200

    logout = client.post(
        "/api/auth/logout", json={"refreshToken": tokens["refreshToken"]}
    )

    assert logout.status_code == 204
    response = _refresh(client, tokens)
    assert response.status_code == 401
    assert _error_code(response) == "INVALID_TOKEN"
    # Logging out twice, or with garbage, is harmless
    assert (
        client.post(
            "/api/auth/logout", json={"refreshToken": tokens["refreshToken"]}
        ).status_code
        == 204
    )
    assert (
        client.post("/api/auth/logout", json={"refreshToken": "garbage"}).status_code
        == 204
    )


def test_refresh_keeps_the_same_session(client, cashier):
    tokens = _login(client)

    renewed = _refresh(client, tokens).json()["data"]

    claims = [
        jwt.decode(t, options={"verify_signature": False})
        for t in (tokens["accessToken"], renewed["accessToken"])
    ]
    assert claims[0]["sid"] == claims[1]["sid"]
    assert "pos:operate" in claims[1]["perms"]


def test_password_change_closes_the_other_sessions(client, cashier):
    phone = _login(client)
    laptop = _login(client)

    response = client.post(
        "/api/auth/change-password",
        json={"currentPassword": PASSWORD, "newPassword": "another-pass-2"},
        headers={"Authorization": f"Bearer {laptop['accessToken']}"},
    )

    assert response.status_code == 204
    assert _refresh(client, laptop).status_code == 200
    assert _refresh(client, phone).status_code == 401


def test_reset_and_deactivation_close_every_session(client, admin_api, cashier):
    tokens = _login(client)
    admin_api.post(
        f"/api/admin/users/{cashier['id']}/reset-password",
        {"newPassword": "temporary-pass"},
    )
    assert _refresh(client, tokens).status_code == 401

    tokens = _login(client, "temporary-pass")
    admin_api.post(f"/api/admin/users/{cashier['id']}/deactivate")
    assert _refresh(client, tokens).status_code == 401


def test_the_last_admin_stays(client, admin_api, auth_headers):
    [me] = [u for u in admin_api.get("/api/admin/users") if u["role"] == 1]

    deactivate = admin_api.error("POST", f"/api/admin/users/{me['id']}/deactivate", 409)
    demote = admin_api.error(
        "PUT", f"/api/admin/users/{me['id']}/role", 409, json={"role": 2}
    )

    assert deactivate["code"] == demote["code"] == "LAST_ADMIN"
    other = admin_api.post(
        "/api/admin/users",
        {
            "username": "admin2",
            "email": "admin2@test.local",
            "password": PASSWORD,
            "role": 1,
        },
    )
    admin_api.put(f"/api/admin/users/{me['id']}/role", {"role": 2})
    assert other["role"] == 1
