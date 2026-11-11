"""Credit sales and accounts receivable against PostgreSQL (S5.5): the credit
limit, also under concurrent sales, payments on account in the shift's cash,
the statement and the aging, and refunds and cancellations of a sale on
credit."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from config import config
from src.auth.domain.entities import Role
from src.shared.infra.outbox.models import OutboxMessageModel
from tests.contract.contracts import errors, validator
from tests.integration.postgres.api import (
    Api,
    at_terminal,
    concurrently,
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
def terminal(admin_api) -> dict:
    shelf = make_location(admin_api, make_warehouse(admin_api)["id"])
    terminal = make_terminal(admin_api, shelf["id"])
    return {**terminal, "shelf": shelf}


@pytest.fixture
def api(client, auth_headers, terminal) -> Api:
    return Api(
        client, at_terminal(auth_headers(Role.CASHIER, full_name="Ana"), terminal)
    )


@pytest.fixture
def manager(client, auth_headers, terminal) -> Api:
    """Approves refunds"""
    return Api(
        client,
        at_terminal(auth_headers(Role.MANAGER, full_name="Gerente"), terminal),
    )


@pytest.fixture
def product(admin_api, terminal) -> dict:
    """10.00 + VAT 15 % = 11.50 a unit, 10 units on the terminal's shelf"""
    product = make_product(admin_api, salePrice="10.00", taxCode="VAT_15")
    make_movement(admin_api, product["id"], 10, terminal["shelf"]["id"])
    return product


@pytest.fixture
def builder(admin_api) -> dict:
    """A customer with a credit limit of 100.00 and 30 days to pay"""
    customer = make_customer(admin_api, seed=51, name="Constructora")
    return admin_api.put(
        f"/api/admin/customers/{customer['id']}",
        {
            "name": "Constructora",
            "taxId": customer["taxId"],
            "taxType": 2,
            "creditLimit": 100,
            "paymentTerms": 30,
        },
    )


@pytest.fixture
def shift(api) -> dict:
    return api.post("/api/pos/shifts/open", {"openingBalance": "100.00"})


def _sale(customer: dict, product: dict, units: int, cash: str = "0") -> dict:
    """`units` at 11.50, `cash` down and the rest on credit"""
    total = Decimal("11.50") * units
    payments = [{"amount": cash, "paymentMethod": "CASH"}] if Decimal(cash) else []
    payments.append({"amount": str(total - Decimal(cash)), "paymentMethod": "CREDIT"})
    return {
        "customerId": customer["id"],
        "items": [{"productId": product["id"], "quantity": units}],
        "payments": payments,
    }


def _receivables(admin_api: Api, customer: dict, **params) -> list[dict]:
    return admin_api.get(
        "/api/admin/receivables", params={"customerId": customer["id"], **params}
    )


def test_a_sale_on_credit_opens_its_receivable(api, admin_api, builder, product, shift):
    sale = api.post("/api/pos/sales/quick", _sale(builder, product, 2, cash="3.00"))

    assert sale["paymentStatus"] == "PARTIAL"
    assert [(p["paymentMethod"], p["termDays"]) for p in sale["payments"]] == [
        ("CASH", None),
        ("CREDIT", 30),
    ]
    [receivable] = _receivables(admin_api, builder)
    assert (receivable["amount"], receivable["balance"], receivable["status"]) == (
        20.0,
        20.0,
        "OPEN",
    )
    assert receivable["dueOn"] == (date.today() + timedelta(days=30)).isoformat()
    assert receivable["saleNumber"] == sale["number"]
    account = admin_api.get(f"/api/admin/customer-accounts/{builder['id']}")
    assert (account["outstanding"], account["available"]) == (20.0, 80.0)
    # Only the cash goes to the drawer
    summary = api.get(f"/api/pos/shifts/{shift['id']}/cash-summary")
    assert summary["cashSales"] == 3.0


def test_a_sale_over_the_credit_limit_is_rejected(
    api, admin_api, builder, product, shift
):
    api.post("/api/pos/sales/quick", _sale(builder, product, 4))  # 46.00

    # 46.00 + 57.50 > 100.00
    error = api.error(
        "POST", "/api/pos/sales/quick", 400, json=_sale(builder, product, 5)
    )

    assert error["code"] == "CREDIT_LIMIT_EXCEEDED"
    assert len(_receivables(admin_api, builder)) == 1
    # Its stock went back with the rest of the transaction
    rows = admin_api.get("/api/admin/stock", params={"productId": product["id"]})
    assert sum(row["quantity"] for row in rows) == 6


def test_a_final_consumer_doesnt_buy_on_credit(api, product, shift):
    error = api.error(
        "POST",
        "/api/pos/sales/quick",
        400,
        json={
            "items": [{"productId": product["id"], "quantity": 1}],
            "payments": [{"amount": "11.50", "paymentMethod": "CREDIT"}],
        },
    )

    assert error["code"] == "CREDIT_CUSTOMER_REQUIRED"


def test_concurrent_sales_on_credit_cant_exceed_the_limit(
    api, admin_api, builder, product, shift
):
    """Each fits the limit, both don't: the customer's row lock makes the second
    wait and count the first one's receivable"""
    body = _sale(builder, product, 5)  # 57.50
    responses = concurrently(
        lambda client: client.post(
            "/api/pos/sales/quick", json=body, headers=with_key(api.headers)
        ),
        lambda client: client.post(
            "/api/pos/sales/quick", json=body, headers=with_key(api.headers)
        ),
    )

    assert sorted(r.status_code for r in responses) == [201, 400]
    [rejected] = [r for r in responses if r.status_code == 400]
    assert rejected.json()["errors"][0]["code"] == "CREDIT_LIMIT_EXCEEDED"
    account = admin_api.get(f"/api/admin/customer-accounts/{builder['id']}")
    assert account["outstanding"] == 57.5


def test_a_cash_payment_on_account_lowers_the_balance_and_counts_in_the_shift(
    api, admin_api, builder, product, shift
):
    sale = api.post("/api/pos/sales/quick", _sale(builder, product, 2))  # 23.00

    payment = api.post(
        "/api/pos/customer-payments",
        {"customerId": builder["id"], "amount": "10.00", "paymentMethod": "CASH"},
    )

    assert payment["number"] == f"AB-{date.today().year}-0001"
    assert payment["shiftId"] == shift["id"]
    assert [
        (a["saleNumber"], a["amount"], a["balance"]) for a in payment["applications"]
    ] == [(sale["number"], 10.0, 13.0)]
    # In the statement
    statement = admin_api.get(f"/api/admin/customer-accounts/{builder['id']}/statement")
    assert [(line["type"], line["balance"]) for line in statement["lines"]] == [
        ("SALE", 23.0),
        ("PAYMENT", 13.0),
    ]
    assert statement["closingBalance"] == 13.0
    # In the shift's cash and its close
    summary = api.get(f"/api/pos/shifts/{shift['id']}/cash-summary")
    assert (summary["customerPayments"], summary["expectedBalance"]) == (10.0, 110.0)
    closed = api.post(
        f"/api/pos/shifts/{shift['id']}/close", {"closingBalance": "110.00"}
    )
    assert (closed["expectedBalance"], closed["discrepancy"]) == (110.0, 0.0)
    z = admin_api.get("/api/pos/reports/z-report", params={"shiftId": shift["id"]})
    assert z["cashReconciliation"]["customerPayments"] == 10.0
    assert z["customerPaymentsByMethod"] == [
        {"paymentMethod": "CASH", "count": 1, "total": 10.0}
    ]
    # Paid off outside the cash register (the shift closed), the sale is paid
    admin_api.post(
        "/api/admin/customer-payments",
        {"customerId": builder["id"], "amount": "13.00", "paymentMethod": "TRANSFER"},
    )
    assert admin_api.get(f"/api/admin/sales/{sale['id']}")["paymentStatus"] == "PAID"
    [receivable] = _receivables(admin_api, builder)
    assert receivable["status"] == "PAID"


def test_a_payment_outside_the_cash_register_counts_in_no_shift(
    api, admin_api, builder, product, shift
):
    api.post("/api/pos/sales/quick", _sale(builder, product, 2))

    payment = admin_api.post(
        "/api/admin/customer-payments",
        {
            "customerId": builder["id"],
            "amount": "23.00",
            "paymentMethod": "TRANSFER",
            "reference": "TRF-001",
        },
    )

    assert payment["shiftId"] is None
    summary = api.get(f"/api/pos/shifts/{shift['id']}/cash-summary")
    assert summary["customerPayments"] == 0.0
    error = admin_api.error(
        "POST",
        "/api/admin/customer-payments",
        400,
        json={"customerId": builder["id"], "amount": "1.00", "paymentMethod": "CASH"},
    )
    assert error["code"] == "CUSTOMER_PAYMENT_EXCEEDS_BALANCE"


def test_the_aging_adds_up_to_the_open_balances(
    api, admin_api, builder, product, shift, pg_engine: Engine
):
    for _ in range(4):
        api.post("/api/pos/sales/quick", _sale(builder, product, 1))
    receivables = _receivables(admin_api, builder)
    # Due in 5 days, and 10, 45 and 100 days ago
    with pg_engine.begin() as conn:
        for receivable, days in zip(receivables, (5, -10, -45, -100), strict=True):
            conn.execute(
                text("UPDATE receivables SET due_on = :due WHERE id = :id"),
                {"due": date.today() + timedelta(days=days), "id": receivable["id"]},
            )
    api.post(
        "/api/pos/customer-payments",
        {"customerId": builder["id"], "amount": "1.50", "paymentMethod": "CASH"},
    )

    aging = admin_api.get("/api/admin/receivables/aging")

    open_balances = sum(
        r["balance"] for r in _receivables(admin_api, builder, status="OPEN")
    )
    totals = aging["totals"]
    buckets = ("notDue", "days1To30", "days31To60", "days61To90", "over90")
    assert totals["total"] == pytest.approx(open_balances) == 44.5
    assert sum(totals[b] for b in buckets) == pytest.approx(totals["total"])
    # FIFO paid the one 100 days overdue first
    assert [totals[b] for b in buckets] == [11.5, 11.5, 11.5, 0.0, 10.0]
    [row] = aging["customers"]
    assert (row["customerId"], row["receivables"]) == (builder["id"], 4)
    overdue = admin_api.get(
        "/api/admin/receivables",
        params={"customerId": builder["id"], "overdue": "true"},
    )
    assert len(overdue) == 3


def test_a_refund_of_a_sale_on_credit_goes_to_its_account_first(
    api, manager, admin_api, builder, product, shift
):
    sale = api.post("/api/pos/sales/quick", _sale(builder, product, 2))  # 23.00
    api.post(
        "/api/pos/customer-payments",
        {"customerId": builder["id"], "amount": "5.00", "paymentMethod": "CASH"},
    )
    [item] = api.get(f"/api/pos/sales/{sale['id']}/items")
    one_unit = [{"saleItemId": item["id"], "quantity": 1}]

    refund = api.post(
        "/api/pos/refunds",
        {"originalSaleId": sale["id"], "items": one_unit},
    )
    assert refund["accountCredit"] == 11.5
    processed = manager.post(
        f"/api/pos/refunds/{refund['id']}/process", {"payments": []}
    )
    assert [(p["paymentMethod"], p["amount"]) for p in processed["payments"]] == [
        ("CREDIT", 11.5)
    ]
    [receivable] = _receivables(admin_api, builder)
    assert receivable["balance"] == 6.5

    # The rest exceeds the balance: 6.50 to the account, 5.00 back in cash
    refund = api.post(
        "/api/pos/refunds",
        {"originalSaleId": sale["id"], "items": one_unit},
    )
    assert refund["accountCredit"] == 6.5
    manager.error(
        "POST",
        f"/api/pos/refunds/{refund['id']}/process",
        422,
        json={"payments": [{"amount": "11.50", "paymentMethod": "CASH"}]},
    )
    manager.post(
        f"/api/pos/refunds/{refund['id']}/process",
        {"payments": [{"amount": "5.00", "paymentMethod": "CASH"}]},
    )
    [receivable] = _receivables(admin_api, builder)
    assert (receivable["balance"], receivable["status"]) == (0.0, "PAID")
    summary = api.get(f"/api/pos/shifts/{shift['id']}/cash-summary")
    assert (summary["cashRefunds"], summary["customerPayments"]) == (5.0, 5.0)
    statement = admin_api.get(f"/api/admin/customer-accounts/{builder['id']}/statement")
    assert [line["type"] for line in statement["lines"]] == [
        "SALE",
        "PAYMENT",
        "REFUND",
        "REFUND",
    ]
    assert statement["closingBalance"] == 0.0


def test_a_sale_on_credit_is_cancelled_only_without_payments_on_account(
    api, admin_api, builder, product, shift
):
    untouched = api.post("/api/pos/sales/quick", _sale(builder, product, 1))
    paid = api.post("/api/pos/sales/quick", _sale(builder, product, 1))
    api.post(
        "/api/pos/customer-payments",
        {
            "customerId": builder["id"],
            "amount": "1.00",
            "paymentMethod": "CASH",
            "applications": [
                {
                    "receivableId": _receivables(admin_api, builder)[1]["id"],
                    "amount": "1.00",
                }
            ],
        },
    )

    api.post(f"/api/pos/sales/{untouched['id']}/cancel", {"reason": "Error"})
    error = api.error("POST", f"/api/pos/sales/{paid['id']}/cancel", 400, json={})

    assert error["code"] == "RECEIVABLE_HAS_PAYMENTS"
    statuses = {r["saleId"]: r["status"] for r in _receivables(admin_api, builder)}
    assert statuses == {untouched["id"]: "CANCELLED", paid["id"]: "OPEN"}
    account = admin_api.get(f"/api/admin/customer-accounts/{builder['id']}")
    assert account["outstanding"] == 10.5


def test_the_invoice_of_a_sale_on_credit_says_its_terms(
    api, admin_api, builder, product, shift, db_session: Session, monkeypatch
):
    monkeypatch.setattr(config, "KAFKA_ENABLED", True)
    sale = api.post("/api/pos/sales/quick", _sale(builder, product, 2, cash="3.00"))

    # Sent again: the same pagos, and the sale stays pending its collection
    resent = admin_api.post(f"/api/admin/sales/{sale['id']}/request-invoice")

    assert resent["paymentStatus"] == "PARTIAL"
    messages = db_session.scalars(
        select(OutboxMessageModel).order_by(OutboxMessageModel.id)
    ).all()
    assert len(messages) == 2
    schema = validator("sales.confirmed", 3)
    for message in messages:
        assert errors(schema, message.payload) == []
        assert message.payload["payload"]["payments"] == [
            {"method": "CASH", "amount": "3.00"},
            {"method": "CREDIT", "amount": "20.00", "term_days": 30},
        ]
