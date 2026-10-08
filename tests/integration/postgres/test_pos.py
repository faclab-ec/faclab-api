"""POS flows against PostgreSQL: shift, checkout, stock effects, refunds and
the shift reports."""

import pytest

from src.auth.domain.entities import Role
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
def api(client, auth_headers) -> Api:
    return Api(client, auth_headers(Role.CASHIER))


@pytest.fixture
def product(admin_api) -> dict:
    """A VAT 15% product priced at 10.00 with 10 units on a shelf."""
    warehouse = make_warehouse(admin_api)
    shelf = make_location(admin_api, warehouse["id"])
    product = make_product(admin_api, salePrice="10.00", taxCode="VAT_15")
    make_movement(admin_api, product["id"], 10, shelf["id"])
    return product


@pytest.fixture
def shift(api) -> dict:
    return api.post(
        "/api/pos/shifts/open", {"cashierName": "Caja 1", "openingBalance": "100.00"}
    )


def _stock_quantity(admin_api: Api, product_id: int) -> int:
    rows = admin_api.get("/api/admin/stock", params={"productId": product_id})
    return sum(row["quantity"] for row in rows)


def _quick_sale(api: Api, product_id: int, quantity: int, amount: str, **extra):
    return api.post(
        "/api/pos/sales/quick",
        {
            "items": [{"productId": product_id, "quantity": quantity}],
            "payments": [
                {"amount": amount, "paymentMethod": extra.pop("method", "CASH")}
            ],
            **extra,
        },
    )


def test_quick_sale_with_card_and_global_discount(api, admin_api, product, shift):
    sale = _quick_sale(
        api,
        product["id"],
        2,
        "20.70",
        method="CREDIT_CARD",
        discountType="PERCENTAGE",
        discountValue="10",
    )

    # VAT is charged on the discounted base: (20 - 2) * 15% = 2.70
    assert (sale["subtotal"], sale["discount"], sale["tax"], sale["total"]) == (
        20.0,
        2.0,
        2.7,
        20.7,
    )
    assert sale["status"] == "CONFIRMED"
    assert sale["paymentStatus"] == "PAID"
    assert sale["shiftId"] == shift["id"]
    assert _stock_quantity(admin_api, product["id"]) == 8

    receipt = api.get(f"/api/pos/sales/{sale['id']}/receipt")
    assert receipt["total"] == 20.7
    assert receipt["change"] == 0


def test_failed_checkout_rolls_back_the_whole_sale(api, admin_api, product, shift):
    error = api.error(
        "POST",
        "/api/pos/sales/quick",
        400,
        json={
            "items": [{"productId": product["id"], "quantity": 11}],
            "payments": [{"amount": "126.50", "paymentMethod": "CASH"}],
        },
    )

    assert error["code"] == "INSUFFICIENT_STOCK"
    assert admin_api.get("/api/admin/sales") == []
    assert _stock_quantity(admin_api, product["id"]) == 10


def test_step_by_step_sale_then_cancel_restores_stock(api, admin_api, product, shift):
    sale = api.post("/api/pos/sales", {"isFinalConsumer": True})
    api.post(
        f"/api/pos/sales/{sale['id']}/items",
        {"productId": product["id"], "quantity": 3, "unitPrice": "10.00"},
    )
    api.post(
        f"/api/pos/sales/{sale['id']}/payments",
        {"amount": "34.50", "paymentMethod": "DEBIT_CARD"},
    )

    confirmed = api.post(f"/api/pos/sales/{sale['id']}/confirm")
    assert confirmed["total"] == 34.5
    assert _stock_quantity(admin_api, product["id"]) == 7

    cancelled = api.post(f"/api/pos/sales/{sale['id']}/cancel")
    assert cancelled["status"] == "CANCELLED"
    assert _stock_quantity(admin_api, product["id"]) == 10


def test_refund_returns_stock_and_cash(
    api, admin_api, client, auth_headers, product, shift
):
    manager = Api(client, auth_headers(Role.MANAGER))
    sale = _quick_sale(api, product["id"], 2, "23.00")
    [item] = api.get(f"/api/pos/sales/{sale['id']}/items")

    refund = api.post(
        "/api/pos/refunds",
        {
            "originalSaleId": sale["id"],
            "items": [{"saleItemId": item["id"], "quantity": 1}],
        },
    )
    assert refund["total"] == 11.5

    processed = manager.post(
        f"/api/pos/refunds/{refund['id']}/process",
        {"payments": [{"amount": "11.50", "paymentMethod": "CASH"}]},
    )
    assert processed["status"] == "COMPLETED"
    assert _stock_quantity(admin_api, product["id"]) == 9

    api.error(
        "POST",
        "/api/pos/refunds",
        400,
        json={
            "originalSaleId": sale["id"],
            "items": [{"saleItemId": item["id"], "quantity": 2}],
        },
    )

    summary = api.get(f"/api/pos/shifts/{shift['id']}/cash-summary")
    assert summary["cashSales"] == 23.0
    assert summary["cashRefunds"] == 11.5
    assert summary["expectedBalance"] == 111.5


def test_shift_reports_and_close(api, product, shift):
    _quick_sale(api, product["id"], 1, "11.50")
    _quick_sale(api, product["id"], 1, "11.50", method="TRANSFER")

    x_report = api.get("/api/pos/reports/x-report", params={"shiftId": shift["id"]})
    assert x_report["salesSummary"]["count"] == 2
    assert x_report["salesSummary"]["total"] == 23.0

    daily = api.get("/api/pos/reports/daily")
    assert daily["totalSales"] == 2

    closed = api.post(
        f"/api/pos/shifts/{shift['id']}/close", {"closingBalance": "111.50"}
    )
    assert closed["status"] == "CLOSED"
    assert closed["expectedBalance"] == 111.5
    assert closed["discrepancy"] == 0
