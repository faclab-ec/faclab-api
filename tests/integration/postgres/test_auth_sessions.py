"""Sessions against PostgreSQL: the refresh token travels in an HttpOnly cookie
and rotates, a reused one revokes the session, repeated failures lock the
login, and refresh stops working after logout, a password change or
deactivation. The last admin can't be removed."""

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.auth.infra.cookies import REFRESH_COOKIE
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
            "fullName": "Caja Uno",
        },
    )


def _device(client) -> TestClient:
    """A browser of its own: a separate cookie jar."""
    return TestClient(client.app)


def _login(client, password: str = PASSWORD, username: str = "caja1"):
    return _device(client).post(
        "/api/auth/login", json={"username": username, "password": password}
    )


def _session(client, password: str = PASSWORD) -> tuple[dict, str]:
    """Log in; return the body and the refresh cookie."""
    response = _login(client, password)
    assert response.status_code == 200, response.text
    return response.json()["data"], response.cookies[REFRESH_COOKIE]


def _refresh(client, refresh_token: str):
    """Present that refresh token, as a browser holding that cookie would."""
    return _device(client).post(
        "/api/auth/refresh", headers={"Cookie": f"{REFRESH_COOKIE}={refresh_token}"}
    )


def _logout(client, refresh_token: str | None):
    headers = {"Cookie": f"{REFRESH_COOKIE}={refresh_token}"} if refresh_token else {}
    return _device(client).post("/api/auth/logout", headers=headers)


def _error_code(response) -> str:
    return response.json()["errors"][0]["code"]


def _claims(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


def test_login_sets_an_http_only_refresh_cookie(client, cashier):
    response = _login(client)

    assert response.status_code == 200
    assert "refreshToken" not in response.json()["data"]
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{REFRESH_COOKIE}=")
    assert "HttpOnly" in cookie
    assert "Path=/api/auth" in cookie
    assert "SameSite=strict" in cookie
    assert _claims(response.json()["data"]["accessToken"])["name"] == "Caja Uno"


def test_a_browser_refreshes_with_its_cookie_and_gets_a_rotated_one(client, cashier):
    browser = _device(client)
    login = browser.post(
        "/api/auth/login", json={"username": "caja1", "password": PASSWORD}
    )
    first = browser.cookies[REFRESH_COOKIE]

    response = browser.post("/api/auth/refresh")

    assert response.status_code == 200, response.text
    second = browser.cookies[REFRESH_COOKIE]
    assert second != first
    assert _claims(second)["jti"] != _claims(first)["jti"]
    access = [login.json()["data"], response.json()["data"]]
    assert (
        _claims(access[0]["accessToken"])["sid"]
        == _claims(access[1]["accessToken"])["sid"]
    )
    assert "pos:operate" in _claims(access[1]["accessToken"])["perms"]


def test_refresh_without_the_cookie_is_rejected(client, cashier):
    response = _device(client).post("/api/auth/refresh")

    assert response.status_code == 401
    assert _error_code(response) == "INVALID_TOKEN"


def test_reusing_a_refresh_token_revokes_the_session(client, cashier, pg_engine):
    _, first = _session(client)
    second = _refresh(client, first).cookies[REFRESH_COOKIE]
    # Past the grace for the token just replaced
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE auth_sessions SET refreshed_at = refreshed_at - interval '1 hour'"
            )
        )

    reused = _refresh(client, first)

    assert reused.status_code == 401
    assert _error_code(reused) == "TOKEN_REUSED"
    # The revocation was committed although the request failed: the newest
    # token is dead too
    newest = _refresh(client, second)
    assert newest.status_code == 401
    assert _error_code(newest) == "INVALID_TOKEN"
    with pg_engine.connect() as conn:
        revoked_at = conn.scalar(
            text(
                "SELECT s.revoked_at FROM auth_sessions s"
                " JOIN users u ON u.id = s.user_id WHERE u.username = 'caja1'"
            )
        )
    assert revoked_at is not None


def test_two_tabs_refreshing_at_once_keep_the_session(client, cashier):
    _, token = _session(client)

    tab_a = _refresh(client, token)
    tab_b = _refresh(client, token)  # same cookie, right after: within the grace

    assert (tab_a.status_code, tab_b.status_code) == (200, 200)
    a, b = tab_a.cookies[REFRESH_COOKIE], tab_b.cookies[REFRESH_COOKIE]
    assert _claims(a)["jti"] == _claims(b)["jti"]
    assert _refresh(client, b).status_code == 200


def test_logout_ends_the_session_and_clears_the_cookie(client, cashier):
    _, token = _session(client)
    token = _refresh(client, token).cookies[REFRESH_COOKIE]

    logout = _logout(client, token)

    assert logout.status_code == 204
    assert f'{REFRESH_COOKIE}=""' in logout.headers["set-cookie"]
    assert "Max-Age=0" in logout.headers["set-cookie"]
    response = _refresh(client, token)
    assert response.status_code == 401
    assert _error_code(response) == "INVALID_TOKEN"
    # Logging out twice, with garbage or without a cookie is harmless
    assert _logout(client, token).status_code == 204
    assert _logout(client, "garbage").status_code == 204
    assert _logout(client, None).status_code == 204


def test_repeated_failures_lock_the_login(client, cashier, pg_engine):
    for _ in range(5):
        failed = _login(client, "wrong-password")
        assert failed.status_code == 401
        assert _error_code(failed) == "INVALID_CREDENTIALS"

    locked = _login(client)  # the right password

    assert locked.status_code == 429
    assert _error_code(locked) == "LOGIN_LOCKED"
    # Unknown usernames lock the same way, so a lock reveals nothing
    for _ in range(5):
        _login(client, username="ghost")
    assert _error_code(_login(client, username="ghost")) == "LOGIN_LOCKED"

    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE login_failures SET attempted_at = attempted_at - interval '16 minutes'"
            )
        )
    assert _login(client).status_code == 200


def test_password_change_closes_the_other_sessions(client, cashier):
    _, phone = _session(client)
    laptop_body, laptop = _session(client)

    response = client.post(
        "/api/auth/change-password",
        json={"currentPassword": PASSWORD, "newPassword": "another-pass-2"},
        headers={"Authorization": f"Bearer {laptop_body['accessToken']}"},
    )

    assert response.status_code == 204
    assert _refresh(client, laptop).status_code == 200
    assert _refresh(client, phone).status_code == 401


def test_reset_and_deactivation_close_every_session(client, admin_api, cashier):
    _, token = _session(client)
    admin_api.post(
        f"/api/admin/users/{cashier['id']}/reset-password",
        {"newPassword": "temporary-pass"},
    )
    assert _refresh(client, token).status_code == 401

    _, token = _session(client, "temporary-pass")
    admin_api.post(f"/api/admin/users/{cashier['id']}/deactivate")
    assert _refresh(client, token).status_code == 401


def test_the_full_name_can_be_changed_and_cleared(admin_api, cashier):
    renamed = admin_api.put(
        f"/api/admin/users/{cashier['id']}/profile", {"fullName": "María Caja"}
    )
    cleared = admin_api.put(
        f"/api/admin/users/{cashier['id']}/profile", {"fullName": ""}
    )

    assert renamed["fullName"] == "María Caja"
    assert cleared["fullName"] is None


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
