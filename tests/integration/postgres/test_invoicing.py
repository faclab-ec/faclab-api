"""Integration with faclab-invoicing against PostgreSQL: the `sales.confirmed`
message follows its v1 contract and carries the invoice amounts, an authorized
invoice from the `invoices` topic marks the sale as invoiced, and a confirmed
sale can be sent again."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import config
from src.auth.domain.entities import Role
from src.invoicing.infra.invoice_messages import handle_invoice_message
from src.shared.infra.outbox.models import OutboxMessageModel
from tests.contract.contracts import errors, validator
from tests.integration.postgres.api import (
    Api,
    make_customer,
    make_location,
    make_movement,
    make_product,
    make_warehouse,
)


@pytest.fixture
def pos(client, admin, auth_headers) -> tuple[Api, list[tuple[int, str]]]:
    """A cashier with an open shift and three products at different VAT rates."""
    admin_api = Api(client, admin)
    location = make_location(admin_api, make_warehouse(admin_api)["id"])
    products = []
    for sku, price, tax_code in (
        ("A", "3.33", "VAT_15"),
        ("B", "1.10", "VAT_5"),
        ("C", "2.00", "VAT_0"),
    ):
        product = make_product(admin_api, sku, salePrice=price, taxCode=tax_code)
        make_movement(admin_api, product["id"], 10, location["id"])
        products.append((product["id"], price))
    cashier = Api(client, auth_headers(Role.CASHIER))
    cashier.post("/api/pos/shifts/open", {"openingBalance": "0"})
    return cashier, products


def _checkout(
    pos, quantities: list[int], customer_id: int | None = None, **discount
) -> dict:
    cashier, products = pos
    sale = cashier.post(
        "/api/pos/sales",
        {"customerId": customer_id} if customer_id else {"isFinalConsumer": True},
    )
    for (product_id, price), quantity in zip(products, quantities, strict=True):
        if quantity:
            cashier.post(
                f"/api/pos/sales/{sale['id']}/items",
                {"productId": product_id, "quantity": quantity, "unitPrice": price},
            )
    if discount:
        cashier.post(f"/api/pos/sales/{sale['id']}/discount", discount)
    total = cashier.get(f"/api/pos/sales/{sale['id']}")["total"]
    cashier.post(
        f"/api/pos/sales/{sale['id']}/payments",
        {"amount": str(total), "paymentMethod": "CASH"},
    )
    return cashier.post(f"/api/pos/sales/{sale['id']}/confirm")


def _authorized(sale_id: int) -> dict:
    return {
        "type": "InvoiceAuthorized",
        "invoiceId": "3f6c1a52-invoice",
        "saleId": str(sale_id),
        "status": "authorized",
        "occurredAt": "2026-10-08T15:00:00.000Z",
    }


def test_sales_confirmed_lines_add_up_to_the_charged_total(
    pos, db_session: Session, monkeypatch
):
    monkeypatch.setattr(config, "KAFKA_ENABLED", True)

    sale = _checkout(pos, [3, 2, 1], discountType="AMOUNT", discountValue="1.00")

    [message] = db_session.scalars(select(OutboxMessageModel))
    items = message.payload["payload"]["items"]
    bases = sum(Decimal(item["invoice_base"]) for item in items)
    taxes = sum(Decimal(item["invoice_tax"]) for item in items)
    discounts = sum(Decimal(item["invoice_discount"]) for item in items)
    assert bases == Decimal(str(sale["subtotal"])) - Decimal("1.00")
    assert bases + taxes == Decimal(message.payload["payload"]["total"])
    assert discounts == Decimal("1.00")


def test_sales_confirmed_follows_the_v1_contract(
    pos, client, admin, db_session: Session, monkeypatch
):
    monkeypatch.setattr(config, "KAFKA_ENABLED", True)
    # Only name and tax id: no email, phone or address
    customer = make_customer(Api(client, admin))

    _checkout(pos, [1, 1, 1])
    _checkout(pos, [2, 0, 1], customer_id=customer["id"])

    final_consumer, without_contact = db_session.scalars(
        select(OutboxMessageModel).order_by(OutboxMessageModel.id)
    )
    schema = validator("sales.confirmed")
    assert errors(schema, final_consumer.payload) == []
    assert errors(schema, without_contact.payload) == []
    assert final_consumer.payload["payload"]["customer"] is None
    assert without_contact.payload["payload"]["customer"]["email"] is None


def test_authorized_invoice_marks_the_sale_invoiced(pos):
    cashier, _ = pos
    sale = _checkout(pos, [1, 0, 0])

    handle_invoice_message(_authorized(sale["id"]))
    # Kafka can deliver the same message again
    handle_invoice_message(_authorized(sale["id"]))

    assert cashier.get(f"/api/pos/sales/{sale['id']}")["status"] == "INVOICED"
    shift = cashier.get("/api/pos/shifts/active")
    summary = cashier.get(f"/api/pos/shifts/{shift['id']}/cash-summary")
    assert summary["cashSales"] == sale["total"]
    x_report = cashier.get("/api/pos/reports/x-report", params={"shiftId": shift["id"]})
    assert x_report["salesSummary"]["count"] == 1

    [item] = cashier.get(f"/api/pos/sales/{sale['id']}/items")
    refund = cashier.post(
        "/api/pos/refunds",
        {
            "originalSaleId": sale["id"],
            "items": [{"saleItemId": item["id"], "quantity": 1}],
        },
    )
    assert refund["total"] == sale["total"]


def test_other_invoice_results_leave_the_sale_alone(pos):
    cashier, _ = pos
    sale = _checkout(pos, [1, 0, 0])
    cancelled = _checkout(pos, [1, 0, 0])
    cashier.post(f"/api/pos/sales/{cancelled['id']}/cancel")

    handle_invoice_message({**_authorized(sale["id"]), "type": "InvoiceSent"})
    handle_invoice_message({**_authorized(sale["id"]), "type": "InvoiceRejected"})
    # A sale cancelled before the SRI answered needs a credit note, not a retry
    handle_invoice_message(_authorized(cancelled["id"]))
    handle_invoice_message(_authorized(999_999))

    assert cashier.get(f"/api/pos/sales/{sale['id']}")["status"] == "CONFIRMED"
    assert cashier.get(f"/api/pos/sales/{cancelled['id']}")["status"] == "CANCELLED"


def test_a_confirmed_sale_can_be_sent_to_invoicing_again(
    pos, client, admin, db_session: Session, monkeypatch
):
    monkeypatch.setattr(config, "KAFKA_ENABLED", True)
    admin_api = Api(client, admin)
    sale = _checkout(pos, [1, 1, 0])
    movements = admin_api.get("/api/admin/movements")

    resent = admin_api.post(f"/api/admin/sales/{sale['id']}/request-invoice")

    assert resent["status"] == "CONFIRMED"
    first, again = db_session.scalars(
        select(OutboxMessageModel).order_by(OutboxMessageModel.id)
    )
    # Same message, new event id: faclab-invoicing tells redeliveries from resends
    assert (again.topic, again.event_type) == ("sales.confirmed", "SaleConfirmed")
    assert again.event_id != first.event_id
    assert again.payload["event_id"] == again.event_id
    assert again.payload["payload"] == first.payload["payload"]
    # Unlike SaleConfirmed, it doesn't move stock
    assert admin_api.get("/api/admin/movements") == movements


def test_only_confirmed_sales_can_be_sent_again(
    pos, client, admin, db_session: Session, monkeypatch
):
    monkeypatch.setattr(config, "KAFKA_ENABLED", True)
    cashier, _ = pos
    admin_api = Api(client, admin)
    invoiced = _checkout(pos, [1, 0, 0])
    handle_invoice_message(_authorized(invoiced["id"]))
    cancelled = _checkout(pos, [1, 0, 0])
    cashier.post(f"/api/pos/sales/{cancelled['id']}/cancel")

    for sale in (invoiced, cancelled):
        error = admin_api.error(
            "POST", f"/api/admin/sales/{sale['id']}/request-invoice", 400
        )
        assert error["code"] == "INVALID_SALE_STATUS"

    monkeypatch.setattr(config, "KAFKA_ENABLED", False)
    confirmed = _checkout(pos, [1, 0, 0])
    error = admin_api.error(
        "POST", f"/api/admin/sales/{confirmed['id']}/request-invoice", 400
    )
    assert error["code"] == "INVOICING_DISABLED"
    # Only the two checkouts made with Kafka on wrote a message
    assert len(db_session.scalars(select(OutboxMessageModel)).all()) == 2


def test_cashiers_can_send_a_sale_again_but_viewers_cannot(
    pos, client, auth_headers, monkeypatch
):
    monkeypatch.setattr(config, "KAFKA_ENABLED", True)
    cashier, _ = pos
    sale = _checkout(pos, [1, 0, 0])

    cashier.post(f"/api/admin/sales/{sale['id']}/request-invoice")
    viewer = Api(client, auth_headers(Role.VIEWER))
    error = viewer.error("POST", f"/api/admin/sales/{sale['id']}/request-invoice", 403)
    assert error["code"] == "PERMISSION_DENIED"
