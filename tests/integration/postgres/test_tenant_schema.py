"""Two tenants on one schema (S2.3): business identifiers are unique per
tenant, each tenant only sees its rows, and composite foreign keys keep a
relation inside one tenant even when the application doesn't check it (every
reference a route can fill since S2.4)."""

from uuid import UUID

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from src.auth.domain.entities import Role
from tests.integration.postgres.api import (
    Api,
    at_terminal,
    make_customer,
    make_location,
    make_product,
    make_supplier,
    make_terminal,
    make_warehouse,
)
from tests.integration.postgres.tenants import OTHER_TENANT_RUC, ensure_tenant

BARCODE = "7861234567890"


@pytest.fixture
def other_tenant(pg_engine: Engine) -> UUID:
    return ensure_tenant(pg_engine, OTHER_TENANT_RUC)


@pytest.fixture
def api_a(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def api_b(client, auth_headers, other_tenant) -> Api:
    return Api(
        client, auth_headers(Role.ADMIN, tenant_id=other_tenant, username="admin-b")
    )


def _catalog(api: Api) -> dict:
    """The same identifiers in whichever tenant calls it"""
    return {
        "warehouse": make_warehouse(api, "WH1"),
        "product": make_product(api, "SKU-1", barcode=BARCODE),
        "customer": make_customer(api, seed=1),
        "supplier": make_supplier(api, seed=2),
        "unit": api.post(
            "/api/admin/units-of-measure", {"name": "Unidad", "symbol": "u"}
        ),
    }


def test_two_tenants_can_use_the_same_identifiers(api_a, api_b):
    a = _catalog(api_a)
    b = _catalog(api_b)

    assert a["product"]["sku"] == b["product"]["sku"]
    assert a["customer"]["taxId"] == b["customer"]["taxId"]
    assert a["product"]["id"] != b["product"]["id"]
    for path, key in (
        ("/api/admin/products", "product"),
        ("/api/admin/customers", "customer"),
        ("/api/admin/suppliers", "supplier"),
        ("/api/admin/warehouses", "warehouse"),
    ):
        assert [row["id"] for row in api_a.get(path)] == [a[key]["id"]]
        assert [row["id"] for row in api_b.get(path)] == [b[key]["id"]]


def test_identifiers_are_still_unique_inside_a_tenant(api_a, api_b):
    _catalog(api_a)
    _catalog(api_b)

    error = api_a.error(
        "POST", "/api/admin/products", 409, json={"name": "Copy", "sku": "SKU-1"}
    )

    assert error["code"] == "PRODUCT_SKU_ALREADY_EXISTS"


def test_another_tenants_rows_are_not_found(api_a, api_b):
    b = _catalog(api_b)

    api_a.error("GET", f"/api/admin/products/{b['product']['id']}", 404)
    api_a.error("GET", f"/api/admin/customers/{b['customer']['id']}", 404)


def test_purchase_order_numbers_are_per_tenant(api_a, api_b):
    numbers = []
    for api in (api_a, api_b):
        supplier = make_supplier(api)
        order = api.post("/api/admin/purchase-orders", {"supplierId": supplier["id"]})
        numbers.append(order["orderNumber"])

    assert numbers[0] == numbers[1]
    assert numbers[0].endswith("-0001")


def test_a_sale_of_one_tenant_rejects_another_tenants_customer(
    client, auth_headers, api_a, api_b
):
    customer_b = make_customer(api_b, seed=3)
    location = make_location(api_a, make_warehouse(api_a)["id"])
    terminal = make_terminal(api_a, location["id"])
    cashier = Api(client, at_terminal(auth_headers(Role.CASHIER), terminal))
    cashier.post("/api/pos/shifts/open", {"openingBalance": "0"})

    # Creating a sale doesn't look the customer up: only the database stops it
    error = cashier.error(
        "POST", "/api/pos/sales", 422, json={"customerId": customer_b["id"]}
    )

    assert error["code"] == "REFERENCE_NOT_FOUND"


def test_the_database_rejects_a_sale_with_another_tenants_customer(
    pg_engine, api_b, tenant, other_tenant
):
    customer_b = make_customer(api_b, seed=3)
    insert = text(
        "INSERT INTO sales (tenant_id, customer_id, is_final_consumer, status,"
        " subtotal, tax, discount, discount_value, total, payment_status,"
        " created_at) VALUES (:tenant, :customer, false, 'DRAFT', 0, 0, 0, 0, 0,"
        " 'PENDING', now())"
    )

    with pytest.raises(IntegrityError) as error, pg_engine.begin() as conn:
        conn.execute(insert, {"tenant": tenant, "customer": customer_b["id"]})
    with pg_engine.begin() as conn:
        conn.execute(insert, {"tenant": other_tenant, "customer": customer_b["id"]})

    diag = getattr(error.value.orig, "diag", None)
    assert diag is not None
    assert diag.constraint_name == "fk_sales_customer_tenant"


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/admin/products",
            lambda b: {"name": "P", "sku": "P-1", "categoryId": b["category"]},
        ),
        (
            "/api/admin/locations",
            lambda b: {"warehouseId": b["warehouse"], "name": "L", "code": "L1"},
        ),
        (
            "/api/admin/lots",
            lambda b: {
                "productId": b["product"],
                "lotNumber": "LOT-1",
                "initialQuantity": 1,
            },
        ),
    ],
    ids=["product-category", "location-warehouse", "lot-product"],
)
def test_a_reference_to_another_tenants_row_is_rejected(api_a, api_b, path, payload):
    b = {
        "category": api_b.post("/api/admin/categories", {"name": "Cat B"})["id"],
        "warehouse": make_warehouse(api_b, "WH-B")["id"],
        "product": make_product(api_b, "SKU-B")["id"],
    }

    # Nothing looks these ids up: the composite foreign key rejects them
    error = api_a.error("POST", path, 422, json=payload(b))

    assert error["code"] == "REFERENCE_NOT_FOUND"


def test_deleting_a_location_clears_only_the_serials_location(api_a, pg_engine, tenant):
    warehouse = make_warehouse(api_a)
    location = make_location(api_a, warehouse["id"])
    product = make_product(api_a)
    serial = api_a.post(
        "/api/admin/serials",
        {
            "productId": product["id"],
            "serialNumber": "SN-1",
            "locationId": location["id"],
        },
    )

    api_a.delete(f"/api/admin/locations/{location['id']}")

    assert api_a.get(f"/api/admin/serials/{serial['id']}")["locationId"] is None
    with pg_engine.connect() as conn:
        row = conn.execute(
            text("SELECT tenant_id FROM serial_numbers WHERE id = :id"),
            {"id": serial["id"]},
        ).one()
    assert row.tenant_id == tenant
