"""Two tenants on one schema (S2.3): business identifiers are unique per
tenant, each tenant only sees its rows, and composite foreign keys keep a
relation inside one tenant even when the application doesn't check it."""

from uuid import UUID

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from src.auth.domain.entities import Role
from tests.integration.postgres.api import (
    Api,
    make_customer,
    make_product,
    make_supplier,
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
    client, auth_headers, api_b
):
    customer_b = make_customer(api_b, seed=3)
    cashier = Api(client, auth_headers(Role.CASHIER))
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
