"""HTTP layer against PostgreSQL: auth, error envelopes and route wiring."""

import pytest

from src.auth.domain.entities import Role
from tests.integration.postgres.api import (
    Api,
    make_customer,
    make_location,
    make_movement,
    make_product,
    make_supplier,
    make_warehouse,
)


@pytest.fixture
def api(client, admin) -> Api:
    return Api(client, admin)


def test_request_without_token_is_rejected(client):
    response = client.get("/api/admin/warehouses")

    assert response.status_code == 403
    assert response.json()["errors"][0]["code"] == "PERMISSION_DENIED"


def test_role_without_permission_is_rejected(client, auth_headers):
    api = Api(client, auth_headers(Role.CASHIER))

    error = api.error(
        "POST", "/api/admin/warehouses", 403, json={"name": "W", "code": "W"}
    )

    assert error["code"] == "PERMISSION_DENIED"


def test_invalid_body_uses_the_error_envelope(api):
    error = api.error("POST", "/api/admin/warehouses", 422, json={"name": "Main"})

    assert error["code"] == "VALIDATION_ERROR"
    assert error["field"] == "body.code"


def test_locations_are_filtered_by_warehouse_and_paginated(api, client, admin):
    main = make_warehouse(api, "MAIN")
    other = make_warehouse(api, "OTHER")
    for code in ("A1", "A2", "A3"):
        make_location(api, main["id"], code)
    make_location(api, other["id"], "B1")

    response = client.get(
        "/api/admin/locations",
        params={"warehouseId": main["id"], "limit": 2},
        headers=admin,
    )

    body = response.json()
    assert response.status_code == 200
    assert len(body["data"]) == 2
    assert {loc["warehouseId"] for loc in body["data"]} == {main["id"]}
    assert body["meta"]["pagination"] == {"total": 3, "limit": 2, "offset": 0}


def test_updating_a_customer_contact_keeps_its_customer(api):
    customer = make_customer(api)
    contact = api.post(
        f"/api/admin/customers/{customer['id']}/contacts", {"name": "Ana"}
    )

    updated = api.put(
        f"/api/admin/customer-contacts/{contact['id']}",
        {"name": "Ana María", "email": "ana@example.com"},
    )

    assert updated["customerId"] == customer["id"]
    assert updated["name"] == "Ana María"


def test_updating_a_supplier_contact_keeps_its_supplier(api):
    supplier = make_supplier(api)
    contact = api.post(
        f"/api/admin/suppliers/{supplier['id']}/contacts", {"name": "Luis"}
    )

    updated = api.put(
        f"/api/admin/supplier-contacts/{contact['id']}", {"name": "Luis P."}
    )

    assert updated["supplierId"] == supplier["id"]


def test_stock_lists_product_and_location_names(api):
    warehouse = make_warehouse(api)
    location = make_location(api, warehouse["id"])
    product = make_product(api)
    make_movement(api, product["id"], 5, location["id"])

    [stock] = api.get("/api/admin/stock", params={"productId": product["id"]})

    assert stock["quantity"] == 5
    assert stock["productName"] == product["name"]
    assert stock["locationName"] == location["name"]


def test_product_with_movements_cannot_be_deleted(api):
    warehouse = make_warehouse(api)
    location = make_location(api, warehouse["id"])
    product = make_product(api)
    make_movement(api, product["id"], 3, location["id"])

    error = api.error("DELETE", f"/api/admin/products/{product['id']}", 409)

    assert error["code"] == "INTEGRITY_ERROR"
    assert api.get(f"/api/admin/products/{product['id']}")["id"] == product["id"]
