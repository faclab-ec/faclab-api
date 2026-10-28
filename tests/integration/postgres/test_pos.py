"""POS flows against PostgreSQL, at a terminal (S2.6): shift, checkout, stock of
the terminal's location, numbering per branch, refunds, the shift reports and
the branch rules, some of them with concurrent requests."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.auth.domain.entities import Role
from tests.integration.postgres.api import (
    Api,
    at_terminal,
    concurrently,
    make_branch,
    make_customer,
    make_location,
    make_movement,
    make_product,
    make_terminal,
    make_warehouse,
    with_key,
)


@pytest.fixture
def admin_api(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def shelf(admin_api) -> dict:
    """A location of a warehouse of the main branch (001)"""
    return make_location(admin_api, make_warehouse(admin_api)["id"])


@pytest.fixture
def terminal(admin_api, shelf) -> dict:
    """Terminal CAJA-01 of branch 001, which sells from the shelf"""
    return make_terminal(admin_api, shelf["id"])


@pytest.fixture
def cashier(auth_headers) -> dict[str, str]:
    return auth_headers(Role.CASHIER, full_name="Ana Cajera")


@pytest.fixture
def api(client, cashier, terminal) -> Api:
    return Api(client, at_terminal(cashier, terminal))


@pytest.fixture
def product(admin_api, shelf) -> dict:
    """A VAT 15% product priced at 10.00 with 10 units on the terminal's shelf."""
    product = make_product(admin_api, salePrice="10.00", taxCode="VAT_15")
    make_movement(admin_api, product["id"], 10, shelf["id"])
    return product


@pytest.fixture
def shift(api) -> dict:
    return api.post("/api/pos/shifts/open", {"openingBalance": "100.00"})


@pytest.fixture
def north(admin_api) -> dict:
    """Branch 002 with its own warehouse, location and terminal CAJA-01"""
    branch = make_branch(admin_api, "002", "Norte")
    warehouse = make_warehouse(admin_api, "WH-N", branch_id=branch["id"])
    location = make_location(admin_api, warehouse["id"], "N1")
    terminal = make_terminal(admin_api, location["id"], branch_id=branch["id"])
    return {"branch": branch, "location": location, "terminal": terminal}


def _stock_quantity(admin_api: Api, product_id: int, location_id: int | None = None):
    params = {"productId": product_id}
    if location_id is not None:
        params["locationId"] = location_id
    rows = admin_api.get("/api/admin/stock", params=params)
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


def _open(headers: dict[str, str]) -> Callable[[TestClient], Response]:
    return lambda client: client.post(
        "/api/pos/shifts/open", json={"openingBalance": "0"}, headers=headers
    )


def _checkout(
    headers: dict[str, str], product_id: int, amount: str = "11.50"
) -> Callable[[TestClient], Response]:
    return lambda client: client.post(
        "/api/pos/sales/quick",
        json={
            "items": [{"productId": product_id, "quantity": 1}],
            "payments": [{"amount": amount, "paymentMethod": "CASH"}],
        },
        headers=with_key(headers),
    )


def test_pos_lists_the_customers(api, admin_api):
    customer = make_customer(admin_api, seed=5, name="Cliente POS")

    customers = api.get("/api/pos/customers")

    assert [c["id"] for c in customers] == [customer["id"]]


def test_quick_sale_with_card_and_global_discount(
    api, admin_api, terminal, product, shift
):
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
    assert (sale["branchId"], sale["emissionPointId"], sale["terminalId"]) == (
        terminal["branchId"],
        terminal["emissionPointId"],
        terminal["id"],
    )
    assert sale["number"] == "V-001-000001"
    assert _stock_quantity(admin_api, product["id"]) == 8

    receipt = api.get(f"/api/pos/sales/{sale['id']}/receipt")
    assert receipt["total"] == 20.7
    assert receipt["change"] == 0
    assert receipt["number"] == "V-001-000001"
    assert receipt["branch"]["establishmentCode"] == "001"
    assert receipt["terminal"]["code"] == "CAJA-01"
    assert receipt["cashier"] == "Ana Cajera"


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
    # It used no number either
    assert _quick_sale(api, product["id"], 1, "11.50")["number"] == "V-001-000001"


def test_step_by_step_sale_then_cancel_restores_stock(api, admin_api, product, shift):
    sale = api.post("/api/pos/sales", {"isFinalConsumer": True})
    assert sale["number"] is None
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
    assert confirmed["number"] == "V-001-000001"
    assert _stock_quantity(admin_api, product["id"]) == 7

    cancelled = api.post(f"/api/pos/sales/{sale['id']}/cancel")
    assert cancelled["status"] == "CANCELLED"
    # A cancelled sale keeps its number
    assert cancelled["number"] == "V-001-000001"
    assert _stock_quantity(admin_api, product["id"]) == 10


def test_cash_handed_over_in_excess_is_change_not_cash(api, product, shift):
    """The cash register, the reports and the invoice count what the payment
    applied; the receipt shows what was handed over and the change (S3.3)"""
    sale = _quick_sale(api, product["id"], 1, "20.00")

    [payment] = api.get(f"/api/pos/sales/{sale['id']}/payments")
    assert (payment["amount"], payment["amountTendered"], payment["change"]) == (
        11.5,
        20.0,
        8.5,
    )
    receipt = api.get(f"/api/pos/sales/{sale['id']}/receipt")
    assert (receipt["totalPaid"], receipt["change"]) == (11.5, 8.5)
    assert receipt["payments"][0]["amountTendered"] == 20.0

    summary = api.get(f"/api/pos/shifts/{shift['id']}/cash-summary")
    assert (summary["cashSales"], summary["expectedBalance"]) == (11.5, 111.5)
    x_report = api.get("/api/pos/reports/x-report", params={"shiftId": shift["id"]})
    assert [m["total"] for m in x_report["paymentsByMethod"]] == [11.5]
    closed = api.post(
        f"/api/pos/shifts/{shift['id']}/close", {"closingBalance": "111.50"}
    )
    assert closed["discrepancy"] == 0


def test_a_sale_of_a_million_and_a_half_is_stored_and_read(
    api, admin_api, shelf, shift
):
    """Up to 999,999.99 until S3.3 (numeric(12, 6)): G-31"""
    product = make_product(
        admin_api, "SKU-BIG", salePrice="1500000.00", taxCode="VAT_0"
    )
    make_movement(admin_api, product["id"], 1, shelf["id"])

    sale = _quick_sale(api, product["id"], 1, "1500000.00")

    assert sale["total"] == 1_500_000.0
    assert api.get(f"/api/pos/sales/{sale['id']}")["total"] == 1_500_000.0
    receipt = api.get(f"/api/pos/sales/{sale['id']}/receipt")
    assert (receipt["total"], receipt["totalPaid"]) == (1_500_000.0, 1_500_000.0)
    summary = api.get(f"/api/pos/shifts/{shift['id']}/cash-summary")
    assert summary["expectedBalance"] == 1_500_100.0


def test_a_sale_is_confirmed_once_paid_and_cancelled_takes_no_payments(
    api, admin_api, product, shift
):
    sale = api.post("/api/pos/sales", {"isFinalConsumer": True})
    api.post(
        f"/api/pos/sales/{sale['id']}/items",
        {"productId": product["id"], "quantity": 3, "unitPrice": "10.00"},
    )
    api.post(
        f"/api/pos/sales/{sale['id']}/payments",
        {"amount": "20.00", "paymentMethod": "DEBIT_CARD"},
    )

    error = api.error("POST", f"/api/pos/sales/{sale['id']}/confirm", 400)
    assert error["code"] == "INSUFFICIENT_PAYMENT"
    assert _stock_quantity(admin_api, product["id"]) == 10
    error = api.error(
        "POST",
        f"/api/pos/sales/{sale['id']}/payments",
        400,
        json={"amount": "20.00", "paymentMethod": "TRANSFER"},
    )
    assert error["code"] == "PAYMENT_EXCEEDS_BALANCE"

    cash = api.post(
        f"/api/pos/sales/{sale['id']}/payments",
        {"amount": "20.00", "paymentMethod": "CASH"},
    )
    assert (cash["amount"], cash["change"]) == (14.5, 5.5)
    confirmed = api.post(f"/api/pos/sales/{sale['id']}/confirm")
    assert (confirmed["status"], confirmed["paymentStatus"]) == ("CONFIRMED", "PAID")

    api.post(f"/api/pos/sales/{sale['id']}/cancel")
    error = api.error(
        "POST",
        f"/api/pos/sales/{sale['id']}/payments",
        400,
        json={"amount": "1.00", "paymentMethod": "CASH"},
    )
    assert error["code"] == "SALE_NOT_PAYABLE"


def test_refund_returns_stock_and_cash(
    api, admin_api, client, auth_headers, terminal, shelf, product, shift
):
    manager = Api(client, at_terminal(auth_headers(Role.MANAGER), terminal))
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
    assert (refund["branchId"], refund["terminalId"]) == (
        terminal["branchId"],
        terminal["id"],
    )
    assert refund["number"] is None

    processed = manager.post(
        f"/api/pos/refunds/{refund['id']}/process",
        {"payments": [{"amount": "11.50", "paymentMethod": "CASH"}]},
    )
    assert processed["status"] == "COMPLETED"
    assert processed["number"] == "D-001-000001"
    assert _stock_quantity(admin_api, product["id"], shelf["id"]) == 9

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


def test_shift_reports_and_close(api, terminal, product, shift):
    _quick_sale(api, product["id"], 1, "11.50")
    _quick_sale(api, product["id"], 1, "11.50", method="TRANSFER")

    x_report = api.get("/api/pos/reports/x-report", params={"shiftId": shift["id"]})
    assert x_report["salesSummary"]["count"] == 2
    assert x_report["salesSummary"]["total"] == 23.0
    assert x_report["shift"]["terminalId"] == terminal["id"]

    daily = api.get("/api/pos/reports/daily")
    assert daily["totalSales"] == 2

    closed = api.post(
        f"/api/pos/shifts/{shift['id']}/close", {"closingBalance": "111.50"}
    )
    assert closed["status"] == "CLOSED"
    assert closed["expectedBalance"] == 111.5
    assert closed["discrepancy"] == 0
    assert closed["closedBy"] == "Ana Cajera"


def test_refund_returns_what_was_charged_after_a_sale_discount(
    api, client, auth_headers, terminal, product, shift
):
    manager = Api(client, at_terminal(auth_headers(Role.MANAGER), terminal))
    sale = _quick_sale(
        api,
        product["id"],
        2,
        "20.70",
        discountType="PERCENTAGE",
        discountValue="10",
    )
    [item] = api.get(f"/api/pos/sales/{sale['id']}/items")

    refund = api.post(
        "/api/pos/refunds",
        {
            "originalSaleId": sale["id"],
            "items": [{"saleItemId": item["id"], "quantity": 1}],
        },
    )

    # Half of the 20.70 charged: base 9.00 + VAT 1.35
    assert (refund["subtotal"], refund["tax"], refund["total"]) == (9.0, 1.35, 10.35)
    manager.post(
        f"/api/pos/refunds/{refund['id']}/process",
        {"payments": [{"amount": "10.35", "paymentMethod": "CASH"}]},
    )


def test_sale_totals_are_charged_in_whole_cents(api, admin_api, shelf, shift):
    candy = make_product(admin_api, "CANDY", salePrice="0.15", taxCode="VAT_15")
    make_movement(admin_api, candy["id"], 10, shelf["id"])

    # 3 x 0.15 = 0.45 + VAT 0.0675 -> 0.07
    sale = _quick_sale(api, candy["id"], 3, "0.52")

    assert (sale["subtotal"], sale["tax"], sale["total"]) == (0.45, 0.07, 0.52)
    assert sale["paymentStatus"] == "PAID"


def test_the_pos_needs_its_terminal(client, cashier, terminal):
    api = Api(client, cashier)

    error = api.error("POST", "/api/pos/shifts/open", 400, json={"openingBalance": 0})

    assert error["code"] == "TERMINAL_REQUIRED"


# Shifts per terminal


def test_two_terminals_open_at_once_but_one_terminal_only_once(
    client, admin_api, cashier, shelf, terminal, pg_engine
):
    second = make_terminal(admin_api, shelf["id"], code="CAJA-02")
    third = make_terminal(admin_api, shelf["id"], code="CAJA-03")

    both = concurrently(
        _open(at_terminal(cashier, terminal)), _open(at_terminal(cashier, second))
    )
    same = concurrently(
        _open(at_terminal(cashier, third)), _open(at_terminal(cashier, third))
    )

    assert sorted(r.status_code for r in both) == [201, 201]
    assert sorted(r.status_code for r in same) == [201, 400]
    [rejected] = [r for r in same if r.status_code == 400]
    assert rejected.json()["errors"][0]["code"] == "SHIFT_ALREADY_OPEN"

    # The database itself refuses a second open shift in the terminal
    with pytest.raises(IntegrityError) as error, pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO pos_shifts (tenant_id, cashier_name, opened_at,"
                " opening_balance, status, terminal_id, branch_id)"
                " SELECT tenant_id, 'Otra', now(), 0, 'OPEN', terminal_id, branch_id"
                " FROM pos_shifts WHERE terminal_id = :terminal"
            ),
            {"terminal": third["id"]},
        )
    diag = getattr(error.value.orig, "diag", None)
    assert diag is not None
    assert diag.constraint_name == "uq_pos_shifts_tenant_terminal_open"


def test_two_terminals_work_with_their_own_shift_and_cash(
    client, admin_api, auth_headers, cashier, shelf, terminal, product
):
    second = make_terminal(admin_api, shelf["id"], code="CAJA-02")
    first_api = Api(client, at_terminal(cashier, terminal))
    second_api = Api(
        client, at_terminal(auth_headers(Role.CASHIER, username="caja-2"), second)
    )
    first_shift = first_api.post("/api/pos/shifts/open", {"openingBalance": "50.00"})
    second_shift = second_api.post("/api/pos/shifts/open", {"openingBalance": "80.00"})

    _quick_sale(first_api, product["id"], 1, "11.50")
    _quick_sale(second_api, product["id"], 2, "23.00")

    assert first_api.get("/api/pos/shifts/active")["id"] == first_shift["id"]
    assert second_api.get("/api/pos/shifts/active")["id"] == second_shift["id"]
    first_cash = first_api.get(f"/api/pos/shifts/{first_shift['id']}/cash-summary")
    second_cash = second_api.get(f"/api/pos/shifts/{second_shift['id']}/cash-summary")
    assert (first_cash["cashSales"], first_cash["expectedBalance"]) == (11.5, 61.5)
    assert (second_cash["cashSales"], second_cash["expectedBalance"]) == (23.0, 103.0)
    daily = first_api.get("/api/pos/reports/daily", params={"terminalId": second["id"]})
    assert (daily["totalSales"], daily["totalAmount"]) == (1, 23.0)
    shifts = admin_api.get("/api/pos/shifts", params={"terminalId": terminal["id"]})
    assert [s["id"] for s in shifts] == [first_shift["id"]]


# Stock of the terminal's location


def test_a_sale_takes_stock_only_from_its_terminals_location(
    api, admin_api, shelf, product, shift
):
    backroom = make_location(admin_api, shelf["warehouseId"], "B1")
    make_movement(admin_api, product["id"], 10, backroom["id"])

    # 20 units in the warehouse, but only 10 where the terminal sells from
    error = api.error(
        "POST",
        "/api/pos/sales/quick",
        400,
        json={
            "items": [{"productId": product["id"], "quantity": 11}],
            "payments": [{"amount": "126.50", "paymentMethod": "CASH"}],
        },
    )
    _quick_sale(api, product["id"], 5, "57.50")

    assert error["code"] == "INSUFFICIENT_STOCK"
    assert _stock_quantity(admin_api, product["id"], shelf["id"]) == 5
    assert _stock_quantity(admin_api, product["id"], backroom["id"]) == 10


def test_a_sale_leaves_the_units_reserved_by_a_transfer(
    api, admin_api, shelf, product, shift
):
    backroom = make_location(admin_api, shelf["warehouseId"], "B1")
    transfer = admin_api.post(
        "/api/admin/transfers",
        {"sourceLocationId": shelf["id"], "destinationLocationId": backroom["id"]},
    )
    admin_api.post(
        f"/api/admin/transfers/{transfer['id']}/items",
        {"productId": product["id"], "quantity": 6},
    )
    admin_api.post(f"/api/admin/transfers/{transfer['id']}/confirm")

    # 10 units on the shelf, 6 of them on their way to the backroom
    error = api.error(
        "POST",
        "/api/pos/sales/quick",
        400,
        json={
            "items": [{"productId": product["id"], "quantity": 5}],
            "payments": [{"amount": "57.50", "paymentMethod": "CASH"}],
        },
    )
    _quick_sale(api, product["id"], 4, "46.00")

    assert error["code"] == "INSUFFICIENT_STOCK"
    assert _stock_quantity(admin_api, product["id"], shelf["id"]) == 6


def test_a_sale_checks_the_total_of_the_lines_of_a_product(
    api, admin_api, shelf, product, shift
):
    error = api.error(
        "POST",
        "/api/pos/sales/quick",
        400,
        json={
            "items": [
                {"productId": product["id"], "quantity": 6},
                {"productId": product["id"], "quantity": 6},
            ],
            "payments": [{"amount": "138.00", "paymentMethod": "CASH"}],
        },
    )

    assert error["code"] == "INSUFFICIENT_STOCK"
    assert "requested=12, available=10" in error["detail"]
    assert _stock_quantity(admin_api, product["id"], shelf["id"]) == 10


def test_an_adjustment_confirmed_after_a_sale_leaves_the_counted_stock(
    api, admin_api, shelf, product, shift
):
    adjustment = admin_api.post(
        "/api/admin/adjustments",
        {"warehouseId": shelf["warehouseId"], "reason": "physical_count"},
    )
    item = admin_api.post(
        f"/api/admin/adjustments/{adjustment['id']}/items",
        {"productId": product["id"], "locationId": shelf["id"], "actualQuantity": 7},
    )
    assert item["expectedQuantity"] == 10
    # A sale between the count and the confirmation
    _quick_sale(api, product["id"], 2, "23.00")

    admin_api.post(f"/api/admin/adjustments/{adjustment['id']}/confirm")

    assert _stock_quantity(admin_api, product["id"], shelf["id"]) == 7
    [confirmed] = admin_api.get(f"/api/admin/adjustments/{adjustment['id']}/items")
    assert (confirmed["expectedQuantity"], confirmed["difference"]) == (8, -1)


def test_a_refund_creates_the_stock_row_where_it_returns_the_goods(
    api, admin_api, client, auth_headers, terminal, shelf, product, shift
):
    manager = Api(client, at_terminal(auth_headers(Role.MANAGER), terminal))
    sale = _quick_sale(api, product["id"], 2, "23.00")
    [item] = api.get(f"/api/pos/sales/{sale['id']}/items")
    # The terminal sells from a location without stock since then
    backroom = make_location(admin_api, shelf["warehouseId"], "B1")
    admin_api.put(
        f"/api/admin/pos-terminals/{terminal['id']}",
        {
            "emissionPointId": terminal["emissionPointId"],
            "defaultLocationId": backroom["id"],
            "code": terminal["code"],
            "name": terminal["name"],
        },
    )
    refund = api.post(
        "/api/pos/refunds",
        {
            "originalSaleId": sale["id"],
            "items": [{"saleItemId": item["id"], "quantity": 1}],
        },
    )

    manager.post(
        f"/api/pos/refunds/{refund['id']}/process",
        {"payments": [{"amount": "11.50", "paymentMethod": "CASH"}]},
    )

    assert _stock_quantity(admin_api, product["id"], backroom["id"]) == 1
    assert _stock_quantity(admin_api, product["id"], shelf["id"]) == 8


def test_concurrent_checkouts_cannot_oversell_the_location(
    api, admin_api, shelf, product, shift
):
    """Both requests read the same stock row; the row lock makes the second
    wait and see what the first one left."""
    responses = concurrently(
        _checkout(api.headers, product["id"], "69.00"),
        _checkout(api.headers, product["id"], "69.00"),
    )

    # Each takes 1: both fit. Then two of 6 each, where only one fits
    assert sorted(r.status_code for r in responses) == [201, 201]
    oversold = concurrently(
        lambda client: client.post(
            "/api/pos/sales/quick",
            json={
                "items": [{"productId": product["id"], "quantity": 6}],
                "payments": [{"amount": "69.00", "paymentMethod": "CASH"}],
            },
            headers=with_key(api.headers),
        ),
        lambda client: client.post(
            "/api/pos/sales/quick",
            json={
                "items": [{"productId": product["id"], "quantity": 6}],
                "payments": [{"amount": "69.00", "paymentMethod": "CASH"}],
            },
            headers=with_key(api.headers),
        ),
    )
    assert sorted(r.status_code for r in oversold) == [201, 400]
    assert _stock_quantity(admin_api, product["id"], shelf["id"]) == 2


def test_cancelling_puts_the_stock_back_where_the_sale_took_it(
    api, admin_api, shelf, terminal, product, shift
):
    sale = _quick_sale(api, product["id"], 4, "46.00")
    # The terminal sells from another location since then
    backroom = make_location(admin_api, shelf["warehouseId"], "B1")
    admin_api.put(
        f"/api/admin/pos-terminals/{terminal['id']}",
        {
            "emissionPointId": terminal["emissionPointId"],
            "defaultLocationId": backroom["id"],
            "code": terminal["code"],
            "name": terminal["name"],
        },
    )

    api.post(f"/api/pos/sales/{sale['id']}/cancel")

    assert _stock_quantity(admin_api, product["id"], shelf["id"]) == 10
    assert _stock_quantity(admin_api, product["id"], backroom["id"]) == 0


# Numbering per branch


def test_concurrent_sales_of_a_branch_get_consecutive_numbers(
    client, admin_api, cashier, shelf, terminal, north
):
    second = make_terminal(admin_api, shelf["id"], code="CAJA-02")
    terminals = [at_terminal(cashier, terminal), at_terminal(cashier, second)]
    for headers in terminals:
        client.post(
            "/api/pos/shifts/open", json={"openingBalance": "0"}, headers=headers
        )
    # One product per sale: they don't wait on each other's stock, only on the
    # branch's counter
    products = []
    for n in range(6):
        product = make_product(admin_api, f"SKU-{n}", salePrice="10.00")
        make_movement(admin_api, product["id"], 5, shelf["id"])
        products.append(product["id"])

    responses = concurrently(
        *(_checkout(terminals[n % 2], product) for n, product in enumerate(products))
    )

    assert [r.status_code for r in responses] == [201] * 6
    numbers = sorted(r.json()["data"]["number"] for r in responses)
    assert numbers == [f"V-001-{n:06d}" for n in range(1, 7)]

    # Another branch has its own correlative
    product = make_product(admin_api, "SKU-N", salePrice="10.00")
    make_movement(admin_api, product["id"], 5, north["location"]["id"])
    north_api = Api(client, at_terminal(cashier, north["terminal"]))
    north_api.post("/api/pos/shifts/open", {"openingBalance": "0"})
    assert _quick_sale(north_api, product["id"], 1, "11.50")["number"] == "V-002-000001"


# Branches


def test_a_cashier_limited_to_a_branch_cant_operate_another(
    client, auth_headers, cashier, terminal, product, north
):
    limited = auth_headers(
        Role.CASHIER, username="caja-matriz", branch_ids=[terminal["branchId"]]
    )
    north_sale_api = Api(client, at_terminal(cashier, north["terminal"]))
    north_sale_api.post("/api/pos/shifts/open", {"openingBalance": "0"})
    north_draft = north_sale_api.post("/api/pos/sales", {"isFinalConsumer": True})
    at_home = Api(client, at_terminal(limited, terminal))
    at_home.post("/api/pos/shifts/open", {"openingBalance": "0"})

    # North's terminal with North's branch: the branch is not theirs
    denied = Api(client, at_terminal(limited, north["terminal"])).error(
        "POST", "/api/pos/shifts/open", 403, json={"openingBalance": "0"}
    )
    # North's terminal with their own branch
    outside = Api(
        client,
        {
            **at_terminal(limited, north["terminal"]),
            "X-Branch-Id": str(terminal["branchId"]),
        },
    ).error("POST", "/api/pos/sales", 400, json={"isFinalConsumer": True})
    # North's sale, by id, from their branch
    unseen = at_home.error("GET", f"/api/pos/sales/{north_draft['id']}", 404)
    not_confirmed = at_home.error(
        "POST", f"/api/pos/sales/{north_draft['id']}/confirm", 404
    )

    assert denied["code"] == "BRANCH_ACCESS_DENIED"
    assert outside["code"] == "POS_TERMINAL_OUTSIDE_BRANCH"
    assert unseen["code"] == not_confirmed["code"] == "NOT_FOUND"
    # Their history only has their branch's shifts
    history = Api(client, limited)
    shifts = history.get("/api/pos/shifts")
    assert {s["branchId"] for s in shifts} == {terminal["branchId"]}
    north_shift = north_sale_api.get("/api/pos/shifts/active")
    history.error("GET", f"/api/pos/shifts/{north_shift['id']}", 404)
    error = history.error(
        "GET", "/api/pos/shifts", 403, params={"branchId": north["branch"]["id"]}
    )
    assert error["code"] == "BRANCH_ACCESS_DENIED"


def test_a_sale_is_refunded_in_its_own_branch(
    api, client, cashier, product, shift, north
):
    sale = _quick_sale(api, product["id"], 1, "11.50")
    [item] = api.get(f"/api/pos/sales/{sale['id']}/items")
    north_api = Api(client, at_terminal(cashier, north["terminal"]))
    north_api.post("/api/pos/shifts/open", {"openingBalance": "0"})

    error = north_api.error(
        "POST",
        "/api/pos/refunds",
        400,
        json={
            "originalSaleId": sale["id"],
            "items": [{"saleItemId": item["id"], "quantity": 1}],
        },
    )

    assert error["code"] == "REFUND_OUTSIDE_BRANCH"


def test_a_pos_request_without_its_headers_is_rejected(client, cashier, shift):
    # Since S2.9 the web always names its branch and terminal: no fallback
    bare = Api(client, cashier)

    error = bare.error(
        "POST", "/api/pos/shifts/open", 400, json={"openingBalance": "0"}
    )
    assert error["code"] == "TERMINAL_REQUIRED"
    error = bare.error(
        "POST",
        f"/api/pos/shifts/{shift['id']}/close",
        400,
        json={"closingBalance": "0"},
    )
    assert error["code"] == "BRANCH_REQUIRED"
