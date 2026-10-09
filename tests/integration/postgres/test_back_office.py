"""Back-office reads against PostgreSQL: the home dashboard, POS shift and
refund history for managers, and price overrides in a quick sale."""

import pytest
from sqlalchemy import select

from src.auth.domain.entities import Role
from src.sales.infra.models import SaleItemModel
from tests.integration.postgres.api import (
    Api,
    make_location,
    make_movement,
    make_product,
    make_warehouse,
)


@pytest.fixture
def admin_api(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def cashier(client, auth_headers) -> Api:
    return Api(client, auth_headers(Role.CASHIER))


@pytest.fixture
def product(admin_api) -> dict:
    """10 units at a purchase price of 6.00, sold at 10.00 + VAT 15%."""
    shelf = make_location(admin_api, make_warehouse(admin_api)["id"])
    product = make_product(admin_api, purchasePrice="6.00", minStock=20)
    make_movement(admin_api, product["id"], 10, shelf["id"])
    return product


def _checkout(cashier: Api, product_id: int, **item) -> dict:
    return cashier.post(
        "/api/pos/sales/quick",
        {
            "items": [{"productId": product_id, "quantity": 1, **item}],
            "payments": [{"amount": "11.50", "paymentMethod": "CASH"}],
        },
    )


def test_dashboard_sums_up_inventory_and_alerts(admin_api, product):
    dashboard = admin_api.get("/api/admin/dashboard")

    assert dashboard["inventoryValue"] == 60.0
    assert [w["totalQuantity"] for w in dashboard["warehouses"]] == [10]
    assert dashboard["alerts"] == {
        "lowStock": 1,
        "outOfStock": 0,
        "reorderPoint": 0,
        "expiringSoon": 0,
    }


def test_managers_read_shift_and_refund_history_newest_first(
    client, auth_headers, cashier, product
):
    manager = Api(client, auth_headers(Role.MANAGER))
    first = cashier.post(
        "/api/pos/shifts/open", {"cashierName": "Caja", "openingBalance": "0"}
    )
    cashier.post(f"/api/pos/shifts/{first['id']}/close", {"closingBalance": "0"})
    second = cashier.post(
        "/api/pos/shifts/open", {"cashierName": "Caja", "openingBalance": "0"}
    )
    sale = _checkout(cashier, product["id"])
    [item] = cashier.get(f"/api/pos/sales/{sale['id']}/items")
    refund = cashier.post(
        "/api/pos/refunds",
        {
            "originalSaleId": sale["id"],
            "items": [{"saleItemId": item["id"], "quantity": 1}],
        },
    )

    shifts = manager.get("/api/pos/shifts")
    assert [s["id"] for s in shifts] == [second["id"], first["id"]]
    assert manager.get(f"/api/pos/shifts/{first['id']}")["status"] == "CLOSED"
    assert [r["id"] for r in manager.get("/api/pos/refunds")] == [refund["id"]]
    # Operating the POS still needs pos:operate
    manager.error("GET", "/api/pos/shifts/active", 403)


def test_quick_sale_records_price_overrides(cashier, db_session, product):
    cashier.post("/api/pos/shifts/open", {"cashierName": "Caja", "openingBalance": "0"})

    error = cashier.error(
        "POST",
        "/api/pos/sales/quick",
        400,
        json={
            "items": [{"productId": product["id"], "quantity": 1, "unitPrice": "9.00"}],
            "payments": [{"amount": "10.35", "paymentMethod": "CASH"}],
        },
    )
    assert error["code"] == "OVERRIDE_REASON_REQUIRED"

    sale = cashier.post(
        "/api/pos/sales/quick",
        {
            "items": [
                {
                    "productId": product["id"],
                    "quantity": 1,
                    "unitPrice": "9.00",
                    "overrideReason": "Producto con empaque dañado",
                }
            ],
            "payments": [{"amount": "10.35", "paymentMethod": "CASH"}],
        },
    )

    [item] = db_session.scalars(
        select(SaleItemModel).where(SaleItemModel.sale_id == sale["id"])
    )
    assert (float(item.price_override), item.override_reason) == (
        9.0,
        "Producto con empaque dañado",
    )
    assert sale["total"] == 10.35
