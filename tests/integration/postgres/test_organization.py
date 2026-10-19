"""Branches, emission points, terminals and access by branch (S2.5), through the
API on PostgreSQL."""

from uuid import UUID

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from src.auth.domain.entities import Role
from tests.integration.postgres.api import (
    Api,
    make_branch,
    make_location,
    make_warehouse,
)
from tests.integration.postgres.tenants import OTHER_TENANT_RUC, ensure_tenant

PASSWORD = "Cajera-Pass-2026!"


@pytest.fixture
def api(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def other_tenant(pg_engine: Engine) -> UUID:
    return ensure_tenant(pg_engine, OTHER_TENANT_RUC)


def _point(api: Api, branch_id: int, code: str = "001") -> dict:
    return api.post("/api/admin/emission-points", {"branchId": branch_id, "code": code})


def _structure(api: Api, code: str) -> dict:
    """A branch with its emission point, warehouse, location and terminal"""
    branch = make_branch(api, code)
    point = _point(api, branch["id"])
    warehouse = make_warehouse(api, f"BOD-{code}", branch_id=branch["id"])
    location = make_location(api, warehouse["id"], f"GEN-{code}")
    terminal = api.post(
        "/api/admin/pos-terminals",
        {
            "branchId": branch["id"],
            "emissionPointId": point["id"],
            "defaultLocationId": location["id"],
            "code": "CAJA-01",
            "name": f"Caja {code}",
        },
    )
    return {
        "branch": branch,
        "point": point,
        "location": location,
        "terminal": terminal,
    }


def _cashier_token(client: TestClient, api: Api, branch_ids: list[int]) -> str:
    """A cashier limited to those branches, logged in after the change"""
    user = api.post(
        "/api/admin/users",
        {
            "username": "cajera",
            "email": "cajera@test.local",
            "password": PASSWORD,
            "role": int(Role.CASHIER),
        },
    )
    access = api.put(
        f"/api/admin/users/{user['id']}/branches", {"branchIds": branch_ids}
    )
    assert access["branchIds"] == sorted(branch_ids)
    login = TestClient(client.app).post(
        "/api/auth/login", json={"username": "cajera", "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return login.json()["data"]["accessToken"]


def _as(token: str, branch_id: int | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if branch_id is not None:
        headers["X-Branch-Id"] = str(branch_id)
    return headers


# Codes


def test_establishment_codes_are_unique_per_tenant(
    api, client, auth_headers, other_tenant
):
    make_branch(api, "001")

    error = api.error(
        "POST",
        "/api/admin/branches",
        409,
        json={"establishmentCode": "001", "name": "Otra"},
    )
    other = Api(
        client, auth_headers(Role.ADMIN, tenant_id=other_tenant, username="admin-b")
    )

    assert error["code"] == "BRANCH_ESTABLISHMENT_CODE_ALREADY_EXISTS"
    assert make_branch(other, "001")["establishmentCode"] == "001"


def test_emission_point_codes_are_unique_per_branch(api):
    first = make_branch(api, "001")
    second = make_branch(api, "002")
    _point(api, first["id"], "001")

    _point(api, second["id"], "001")
    error = api.error(
        "POST",
        "/api/admin/emission-points",
        409,
        json={"branchId": first["id"], "code": "001"},
    )

    assert error["code"] == "EMISSION_POINT_CODE_ALREADY_EXISTS"


@pytest.mark.parametrize("code", ["000", "1", "1000", "A01"])
def test_codes_have_three_digits_from_001_to_999(api, code):
    error = api.error(
        "POST",
        "/api/admin/branches",
        422,
        json={"establishmentCode": code, "name": "Sucursal"},
    )

    assert error["code"] == "VALIDATION_ERROR"


# Warehouses and terminals


def test_a_warehouse_cant_be_created_without_a_branch(api):
    error = api.error(
        "POST", "/api/admin/warehouses", 422, json={"name": "Bodega", "code": "B1"}
    )

    assert error["code"] == "VALIDATION_ERROR"
    assert error["field"] == "body.branchId"


def test_a_warehouse_keeps_its_branch(api):
    branch = make_branch(api, "002")
    warehouse = make_warehouse(api, "B2", branch_id=branch["id"])

    updated = api.put(
        f"/api/admin/warehouses/{warehouse['id']}",
        {"name": "Bodega Norte", "code": "B2"},
    )

    assert updated["branchId"] == branch["id"]
    assert [
        w["id"]
        for w in api.get("/api/admin/warehouses", params={"branchId": branch["id"]})
    ] == [warehouse["id"]]


def test_a_terminal_cant_take_stock_from_another_branch(api):
    north = _structure(api, "001")
    south = _structure(api, "002")

    error = api.error(
        "POST",
        "/api/admin/pos-terminals",
        400,
        json={
            "branchId": north["branch"]["id"],
            "emissionPointId": north["point"]["id"],
            "defaultLocationId": south["location"]["id"],
            "code": "CAJA-02",
            "name": "Caja 2",
        },
    )
    moved = api.error(
        "PUT",
        f"/api/admin/pos-terminals/{north['terminal']['id']}",
        400,
        json={
            "emissionPointId": south["point"]["id"],
            "defaultLocationId": north["location"]["id"],
            "code": "CAJA-01",
            "name": "Caja",
        },
    )

    assert error["code"] == "LOCATION_OUTSIDE_BRANCH"
    assert moved["code"] == "EMISSION_POINT_OUTSIDE_BRANCH"


def test_a_branch_in_use_cant_be_deleted(api):
    north = _structure(api, "001")

    error = api.error("DELETE", f"/api/admin/branches/{north['branch']['id']}", 409)

    assert error["code"] == "RECORD_IN_USE"
    assert api.get(f"/api/admin/branches/{north['branch']['id']}")


# Access by branch


def test_a_user_limited_to_one_branch_cant_use_another(api, client):
    north = _structure(api, "001")
    south = _structure(api, "002")

    token = _cashier_token(client, api, [north["branch"]["id"]])

    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["bids"] == [north["branch"]["id"]]
    own = client.get("/api/pos/terminals", headers=_as(token, north["branch"]["id"]))
    assert own.status_code == 200, own.text
    assert [t["id"] for t in own.json()["data"]] == [north["terminal"]["id"]]
    for path in ("/api/pos/terminals", "/api/pos/products"):
        denied = client.get(path, headers=_as(token, south["branch"]["id"]))
        assert denied.status_code == 403, denied.text
        assert denied.json()["errors"][0]["code"] == "BRANCH_ACCESS_DENIED"
    # Without the header the other routes keep working (until S2.6)
    assert client.get("/api/pos/products", headers=_as(token)).status_code == 200


def test_me_lists_the_branches_the_user_may_enter(api, client):
    north = _structure(api, "001")
    _structure(api, "002")
    token = _cashier_token(client, api, [north["branch"]["id"]])

    me = client.get("/api/auth/me", headers=_as(token)).json()["data"]
    every = api.get("/api/auth/me")

    assert [b["establishmentCode"] for b in me["branches"]] == ["001"]
    assert [b["establishmentCode"] for b in every["branches"]] == ["001", "002"]


def test_without_branches_the_user_may_enter_all_of_them(api, client):
    north = _structure(api, "001")
    south = _structure(api, "002")

    token = _cashier_token(client, api, [])

    assert "bids" not in jwt.decode(token, options={"verify_signature": False})
    for structure in (north, south):
        branch_id = structure["branch"]["id"]
        response = client.get("/api/pos/terminals", headers=_as(token, branch_id))
        assert response.status_code == 200, response.text


def test_the_pos_lists_terminals_only_for_a_branch(api, client):
    north = _structure(api, "001")

    missing = client.get("/api/pos/terminals", headers=api.headers)
    unknown = client.get(
        "/api/pos/terminals", headers={**api.headers, "X-Branch-Id": "999999"}
    )
    api.put(
        f"/api/admin/branches/{north['branch']['id']}",
        {"establishmentCode": "001", "name": "Matriz", "isActive": False},
    )
    inactive = client.get(
        "/api/pos/terminals",
        headers={**api.headers, "X-Branch-Id": str(north["branch"]["id"])},
    )

    assert missing.json()["errors"][0]["code"] == "BRANCH_REQUIRED"
    assert unknown.status_code == 404
    assert inactive.json()["errors"][0]["code"] == "BRANCH_INACTIVE"


def test_another_tenants_branch_cant_be_given_to_a_user(
    api, client, auth_headers, other_tenant
):
    other = Api(
        client, auth_headers(Role.ADMIN, tenant_id=other_tenant, username="admin-b")
    )
    foreign = make_branch(other, "001")
    user = api.post(
        "/api/admin/users",
        {
            "username": "cajera",
            "email": "cajera@test.local",
            "password": PASSWORD,
            "role": int(Role.CASHIER),
        },
    )

    error = api.error(
        "PUT",
        f"/api/admin/users/{user['id']}/branches",
        422,
        json={"branchIds": [foreign["id"]]},
    )

    assert error["code"] == "REFERENCE_NOT_FOUND"
    assert api.get(f"/api/admin/users/{user['id']}/branches")["branchIds"] == []
