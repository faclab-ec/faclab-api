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

    assert error["code"] == "RECORD_IN_USE"
    assert api.get(f"/api/admin/products/{product['id']}")["id"] == product["id"]


@pytest.mark.parametrize(
    ("path", "payload", "code"),
    [
        (
            "/api/admin/products",
            {"name": "Other", "sku": "SKU-1"},
            "PRODUCT_SKU_ALREADY_EXISTS",
        ),
        (
            "/api/admin/products",
            {"name": "Other", "sku": "SKU-2", "barcode": "7860000000001"},
            "PRODUCT_BARCODE_ALREADY_EXISTS",
        ),
        (
            "/api/admin/warehouses",
            {"name": "Other", "code": "WH1"},
            "WAREHOUSE_CODE_ALREADY_EXISTS",
        ),
        (
            "/api/admin/units-of-measure",
            {"name": "Other", "symbol": "u"},
            "UNIT_OF_MEASURE_SYMBOL_ALREADY_EXISTS",
        ),
    ],
)
def test_duplicate_unique_values_return_409(api, path, payload, code):
    make_product(api, "SKU-1", barcode="7860000000001")
    warehouse = make_warehouse(api, "WH1")
    api.post("/api/admin/units-of-measure", {"name": "Unidad", "symbol": "u"})
    if path == "/api/admin/warehouses":
        payload = {**payload, "branchId": warehouse["branchId"]}

    error = api.error("POST", path, 409, json=payload)

    assert error["code"] == code


def test_location_codes_are_unique_per_warehouse(api):
    main = make_warehouse(api, "MAIN")
    other = make_warehouse(api, "OTHER")
    make_location(api, main["id"], "A1")

    make_location(api, other["id"], "A1")
    error = api.error(
        "POST",
        "/api/admin/locations",
        409,
        json={"warehouseId": main["id"], "name": "Again", "code": "A1"},
    )

    assert error["code"] == "LOCATION_CODE_ALREADY_EXISTS"


def test_duplicate_tax_ids_return_409(api):
    customer = make_customer(api, seed=7)
    supplier = make_supplier(api, seed=8)

    customer_error = api.error(
        "POST",
        "/api/admin/customers",
        409,
        json={"name": "Copy", "taxId": customer["taxId"], "taxType": 2},
    )
    supplier_error = api.error(
        "POST",
        "/api/admin/suppliers",
        409,
        json={"name": "Copy", "taxId": supplier["taxId"], "taxType": 1},
    )

    assert customer_error["code"] == "CUSTOMER_TAX_ID_ALREADY_EXISTS"
    assert supplier_error["code"] == "SUPPLIER_TAX_ID_ALREADY_EXISTS"


def test_duplicate_lot_and_serial_return_409(api):
    product = make_product(api)
    lot = {"productId": product["id"], "lotNumber": "L-1", "initialQuantity": 1}
    serial = {"productId": product["id"], "serialNumber": "SN-1"}
    api.post("/api/admin/lots", lot)
    api.post("/api/admin/serials", serial)

    lot_error = api.error("POST", "/api/admin/lots", 409, json=lot)
    serial_error = api.error("POST", "/api/admin/serials", 409, json=serial)

    assert lot_error["code"] == "LOT_ALREADY_EXISTS"
    assert serial_error["code"] == "SERIAL_NUMBER_ALREADY_EXISTS"


def test_referencing_a_missing_record_returns_422(api):
    error = api.error(
        "POST",
        "/api/admin/movements",
        422,
        json={"productId": 999, "quantity": 1, "type": "IN"},
    )

    assert error["code"] == "REFERENCE_NOT_FOUND"


def test_status_errors_carry_a_specific_code_and_detail(api, client):
    supplier = make_supplier(api)
    po = api.post("/api/admin/purchase-orders", {"supplierId": supplier["id"]})
    api.post(f"/api/admin/purchase-orders/{po['id']}/cancel")

    error = api.error("POST", f"/api/admin/purchase-orders/{po['id']}/send", 400)

    assert error["code"] == "INVALID_PURCHASE_ORDER_STATUS"
    assert error["detail"] == "current_status=cancelled, operation=send"
