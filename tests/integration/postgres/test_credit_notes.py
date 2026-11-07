"""Credit notes against PostgreSQL (S4.5): a refund of an invoiced sale asks for one
in its transaction, following the contract of `credit_notes.requested`, a refund made
before the authorization asks for it after, the result reaches the refund and the
sale, the final consumer is blocked (NAC-DGERCGC25-00000014, art. 3) and the invoice
of a cancelled sale is credited from its discrepancy."""

from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from config import config
from src.auth.domain.entities import Role
from src.invoicing.infra.credit_note_messages import handle_credit_note_message
from src.invoicing.infra.invoice_messages import handle_invoice_message
from src.shared.domain.tenant import TenantContext, TenantSource
from src.shared.infra.outbox.models import OutboxMessageModel
from src.shared.infra.tenant import tenant_scope
from tests.contract.contracts import errors, validator
from tests.integration.postgres.api import (
    Api,
    at_terminal,
    make_customer,
    make_location,
    make_movement,
    make_product,
    make_terminal,
    make_warehouse,
)

SCHEMA = validator("credit_notes.requested", 2)
INVOICE_ID = "3f6c1a52-0000-5000-8000-000000000001"
DOCUMENT_ID = "2f3a4b5c-6d7e-5f80-9a1b-2c3d4e5f6a7b"
ACCESS_CODE = "0211202604179999999000110010020000000121234567811"


class Pos:
    def __init__(self, cashier: Api, manager: Api, admin: Api, tenant: UUID, product):
        self.cashier = cashier
        self.manager = manager
        self.admin = admin
        self.tenant = tenant
        self.product = product
        self.customer = make_customer(admin)["id"]

    def sale(self, quantity: int = 2, customer: int | None = None) -> dict:
        body = {
            "items": [{"productId": self.product["id"], "quantity": quantity}],
            "payments": [{"amount": f"{11.5 * quantity:.2f}", "paymentMethod": "CASH"}],
        }
        if customer is not None:
            body["customerId"] = customer
        return self.cashier.post("/api/pos/sales/quick", body)

    def invoice_result(self, sale_id: int, kind: str = "Authorized") -> None:
        with tenant_scope(TenantContext(self.tenant, TenantSource.MESSAGE)):
            handle_invoice_message(
                {
                    "type": f"Invoice{kind}",
                    "invoiceId": INVOICE_ID,
                    "saleId": str(sale_id),
                    "status": kind.lower(),
                    "occurredAt": "2026-10-08T15:00:00.000Z",
                }
            )

    def invoiced_sale(self, quantity: int = 2) -> dict:
        sale = self.sale(quantity, self.customer)
        self.invoice_result(sale["id"])
        return sale

    def item_of(self, sale_id: int) -> dict:
        [item] = self.cashier.get(f"/api/pos/sales/{sale_id}/items")
        return item

    def refund_body(self, sale_id: int, quantity: int = 1, reason=None) -> dict:
        body = {
            "originalSaleId": sale_id,
            "items": [
                {"saleItemId": self.item_of(sale_id)["id"], "quantity": quantity}
            ],
        }
        return {**body, "reason": reason} if reason else body

    def process(self, refund: dict) -> dict:
        return self.manager.post(
            f"/api/pos/refunds/{refund['id']}/process",
            {"payments": [{"amount": refund["total"], "paymentMethod": "CASH"}]},
        )

    def refund(self, sale_id: int, quantity: int = 1) -> dict:
        created = self.cashier.post(
            "/api/pos/refunds",
            self.refund_body(sale_id, quantity, "Producto con defecto"),
        )
        return self.process(created)

    def credit_note_result(self, note_id: int, kind: str = "Authorized", **fields):
        authorized = kind == "Authorized"
        with tenant_scope(TenantContext(self.tenant, TenantSource.MESSAGE)):
            handle_credit_note_message(
                {
                    "event_id": "c1d2e3f4-a5b6-5c7d-8e9f-0a1b2c3d4e51",
                    "event_type": f"CreditNote{kind}",
                    "schema_version": 1,
                    "tenant_id": str(self.tenant),
                    "aggregate_id": note_id,
                    "occurred_at": "2026-11-02T15:04:21.512Z",
                    "payload": {
                        "credit_note_id": note_id,
                        "document_id": DOCUMENT_ID,
                        "sale_id": 1,
                        "number": "001-001-000000012",
                        "access_code": ACCESS_CODE,
                        "authorized_at": (
                            "2026-11-02T15:04:20.000Z" if authorized else None
                        ),
                        "reason": None if authorized else "ERROR 68",
                        **fields,
                    },
                }
            )


@pytest.fixture
def kafka_on(monkeypatch) -> Iterator[None]:
    monkeypatch.setattr(config, "KAFKA_ENABLED", True)
    yield


@pytest.fixture
def pos(client, admin, auth_headers, tenant) -> Pos:
    admin_api = Api(client, admin)
    location = make_location(admin_api, make_warehouse(admin_api)["id"])
    product = make_product(admin_api, "SKU-1", salePrice="10.00", taxCode="VAT_15")
    make_movement(admin_api, product["id"], 50, location["id"])
    terminal = make_terminal(admin_api, location["id"])
    cashier = Api(client, at_terminal(auth_headers(Role.CASHIER), terminal))
    cashier.post("/api/pos/shifts/open", {"openingBalance": "100"})
    manager = Api(client, at_terminal(auth_headers(Role.MANAGER), terminal))
    return Pos(cashier, manager, admin_api, tenant, product)


def _credit_note_messages(session: Session) -> list[OutboxMessageModel]:
    return list(
        session.scalars(
            select(OutboxMessageModel)
            .where(OutboxMessageModel.topic == "credit_notes.requested")
            .order_by(OutboxMessageModel.id)
        )
    )


def test_a_refund_of_an_invoiced_sale_asks_for_its_credit_note(
    pos, kafka_on, db_session: Session, tenant
):
    sale = pos.invoiced_sale()

    refund = pos.refund(sale["id"])

    note = refund["creditNote"]
    assert note["status"] == "PENDING"
    assert (note["saleId"], note["refundId"], note["invoiceId"]) == (
        sale["id"],
        refund["id"],
        INVOICE_ID,
    )
    assert (note["reason"], note["total"]) == ("Producto con defecto", 11.5)
    [message] = _credit_note_messages(db_session)
    assert errors(SCHEMA, message.payload) == []
    assert message.tenant_id == tenant
    payload = message.payload["payload"]
    assert (payload["refund_id"], payload["refund_number"]) == (
        refund["id"],
        refund["number"],
    )
    assert payload["invoice_id"] == INVOICE_ID
    [item] = payload["items"]
    assert (item["product_id"], item["quantity"], item["tax_code"]) == (
        pos.product["id"],
        "1.000000",
        "VAT_15",
    )
    assert (item["invoice_base"], item["invoice_tax"]) == ("10.00", "1.50")
    assert payload["total"] == "11.500000"


def test_the_credit_note_is_written_in_the_transaction_of_the_refund(
    pos, kafka_on, pg_engine: Engine
):
    sale = pos.invoiced_sale()

    refund = pos.refund(sale["id"])

    with pg_engine.connect() as conn:
        transactions = conn.execute(
            text(
                "SELECT (SELECT xmin::text FROM pos_refunds WHERE id = :refund), "
                "(SELECT xmin::text FROM credit_notes WHERE refund_id = :refund), "
                "(SELECT xmin::text FROM outbox_messages "
                " WHERE topic = 'credit_notes.requested')"
            ),
            {"refund": refund["id"]},
        ).one()
    assert len(set(transactions)) == 1


def test_a_failure_writing_the_message_rolls_the_refund_back(
    pos, kafka_on, monkeypatch, pg_engine: Engine, client
):
    sale = pos.invoiced_sale()
    created = pos.cashier.post(
        "/api/pos/refunds", pos.refund_body(sale["id"], reason="Defecto")
    )
    from src.invoicing.infra import event_handlers

    def fail(*_args, **_kwargs):
        raise RuntimeError("no outbox")

    monkeypatch.setattr(event_handlers, "build_credit_note_message", fail)
    failing = type(client)(client.app, raise_server_exceptions=False)

    response = failing.post(
        f"/api/pos/refunds/{created['id']}/process",
        json={"payments": [{"amount": created["total"], "paymentMethod": "CASH"}]},
        headers=pos.manager._headers("POST", {}),
    )

    assert response.status_code == 500
    with pg_engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM pos_refunds WHERE id = :id"), {"id": created["id"]}
        ).scalar_one()
        notes = conn.execute(text("SELECT count(*) FROM credit_notes")).scalar_one()
    assert status == "PENDING"
    assert notes == 0


def test_the_refund_shows_its_credit_note_and_its_result(pos, kafka_on):
    sale = pos.invoiced_sale()
    refund = pos.refund(sale["id"])
    note_id = refund["creditNote"]["id"]

    pos.credit_note_result(note_id)

    shown = pos.manager.get(f"/api/pos/refunds/{refund['id']}")["creditNote"]
    assert (shown["status"], shown["number"], shown["accessCode"]) == (
        "AUTHORIZED",
        "001-001-000000012",
        ACCESS_CODE,
    )
    assert shown["documentId"] == DOCUMENT_ID
    [listed] = pos.manager.get("/api/pos/refunds", params={"saleId": sale["id"]})
    assert listed["creditNote"]["status"] == "AUTHORIZED"


def test_a_refund_made_before_the_authorization_asks_for_it_after(
    pos, kafka_on, db_session: Session
):
    sale = pos.sale(2, pos.customer)
    assert sale["invoiceStatus"] == "PENDING"

    refund = pos.refund(sale["id"])

    # Nothing to refer to yet, and the POS isn't held back by the SRI
    assert refund["status"] == "COMPLETED"
    assert refund["creditNote"] is None
    assert _credit_note_messages(db_session) == []

    pos.invoice_result(sale["id"])

    [message] = _credit_note_messages(db_session)
    assert errors(SCHEMA, message.payload) == []
    assert message.payload["payload"]["refund_id"] == refund["id"]
    assert message.payload["payload"]["invoice_id"] == INVOICE_ID
    shown = pos.manager.get(f"/api/pos/refunds/{refund['id']}")["creditNote"]
    assert shown["status"] == "PENDING"


def test_authorizing_twice_asks_for_the_credit_note_once(
    pos, kafka_on, db_session: Session
):
    sale = pos.sale(2, pos.customer)
    pos.refund(sale["id"])

    pos.invoice_result(sale["id"])
    pos.invoice_result(sale["id"])

    assert len(_credit_note_messages(db_session)) == 1


@pytest.mark.parametrize(
    "authorized", [True, False], ids=["invoiced", "invoice-on-its-way"]
)
def test_a_sale_invoiced_to_the_final_consumer_is_not_refunded(
    pos, kafka_on, authorized
):
    sale = pos.sale(1)
    if authorized:
        pos.invoice_result(sale["id"])

    error = pos.cashier.error(
        "POST",
        "/api/pos/refunds",
        400,
        json=pos.refund_body(sale["id"], reason="Cambio de opinión"),
    )

    assert error["code"] == "FINAL_CONSUMER_REFUND_NOT_ALLOWED"


def test_a_pending_refund_is_blocked_too_when_its_invoice_is_authorized_later(
    pos, kafka_on, client, admin, pg_engine: Engine
):
    """Created while the invoice was rejected: then the sale was sent again"""
    sale = pos.sale(1)
    pos.invoice_result(sale["id"], "Rejected")
    created = pos.cashier.post("/api/pos/refunds", pos.refund_body(sale["id"]))
    Api(client, admin).post(f"/api/admin/sales/{sale['id']}/request-invoice")
    pos.invoice_result(sale["id"])

    error = pos.manager.error(
        "POST",
        f"/api/pos/refunds/{created['id']}/process",
        400,
        json={"payments": [{"amount": created["total"], "paymentMethod": "CASH"}]},
    )

    assert error["code"] == "FINAL_CONSUMER_REFUND_NOT_ALLOWED"


def test_the_policy_lets_it_through_without_a_credit_note(
    pos, kafka_on, monkeypatch, db_session: Session
):
    monkeypatch.setattr(config, "FINAL_CONSUMER_REFUNDS_ALLOWED", True)
    sale = pos.sale(1)
    pos.invoice_result(sale["id"])

    refund = pos.process(
        pos.cashier.post("/api/pos/refunds", pos.refund_body(sale["id"]))
    )

    assert refund["status"] == "COMPLETED"
    assert refund["creditNote"] is None
    assert _credit_note_messages(db_session) == []


def test_a_final_consumer_sale_without_an_invoice_is_still_refunded(pos, db_session):
    """Kafka off: no invoice, nothing to back"""
    sale = pos.sale(1)
    assert sale["invoiceStatus"] is None

    refund = pos.process(
        pos.cashier.post("/api/pos/refunds", pos.refund_body(sale["id"]))
    )

    assert refund["status"] == "COMPLETED"
    assert refund["creditNote"] is None


def test_a_refund_of_a_sale_with_an_invoice_needs_a_reason(pos, kafka_on):
    sale = pos.invoiced_sale()

    error = pos.cashier.error(
        "POST", "/api/pos/refunds", 400, json=pos.refund_body(sale["id"])
    )

    assert error["code"] == "REFUND_REASON_REQUIRED"


def test_a_pending_refund_of_a_sale_cancelled_since_is_not_processed(pos):
    """Its stock already went back with the cancellation"""
    sale = pos.sale(1, pos.customer)
    created = pos.cashier.post("/api/pos/refunds", pos.refund_body(sale["id"]))
    pos.cashier.post(f"/api/pos/sales/{sale['id']}/cancel", {"reason": "Error"})

    error = pos.manager.error(
        "POST",
        f"/api/pos/refunds/{created['id']}/process",
        400,
        json={"payments": [{"amount": created["total"], "paymentMethod": "CASH"}]},
    )

    assert error["code"] == "SALE_NOT_CONFIRMED"


def test_annulling_is_a_total_refund_and_credits_the_invoice(pos, kafka_on):
    sale = pos.invoiced_sale(quantity=2)
    # Cancelling keeps answering what to do
    error = pos.cashier.error(
        "POST", f"/api/pos/sales/{sale['id']}/cancel", 400, json={"reason": "Error"}
    )
    assert error["code"] == "CREDIT_NOTE_REQUIRED"

    refund = pos.refund(sale["id"], quantity=2)
    assert refund["total"] == 23
    assert pos.cashier.get(f"/api/pos/sales/{sale['id']}")["invoiceStatus"] == (
        "AUTHORIZED"
    )

    pos.credit_note_result(refund["creditNote"]["id"])

    shown = pos.cashier.get(f"/api/pos/sales/{sale['id']}")
    assert shown["invoiceStatus"] == "CREDITED"
    # It stays invoiced: cash and reports count what its refund paid back
    assert shown["status"] == "INVOICED"


def test_partial_refunds_credit_the_invoice_only_once_all_are_authorized(pos, kafka_on):
    sale = pos.invoiced_sale(quantity=2)
    first = pos.refund(sale["id"])
    second = pos.refund(sale["id"])

    pos.credit_note_result(first["creditNote"]["id"])
    assert pos.cashier.get(f"/api/pos/sales/{sale['id']}")["invoiceStatus"] == (
        "AUTHORIZED"
    )

    pos.credit_note_result(second["creditNote"]["id"], number="001-001-000000013")
    assert pos.cashier.get(f"/api/pos/sales/{sale['id']}")["invoiceStatus"] == (
        "CREDITED"
    )


def test_a_partial_refund_leaves_the_invoice_authorized(pos, kafka_on):
    sale = pos.invoiced_sale(quantity=2)
    refund = pos.refund(sale["id"])

    pos.credit_note_result(refund["creditNote"]["id"])

    assert pos.cashier.get(f"/api/pos/sales/{sale['id']}")["invoiceStatus"] == (
        "AUTHORIZED"
    )


def test_a_credited_sale_subtracts_its_refund_once_from_the_cash(pos, kafka_on):
    shift = pos.cashier.get("/api/pos/shifts/active")
    sale = pos.invoiced_sale(quantity=2)
    refund = pos.refund(sale["id"], quantity=2)
    pos.credit_note_result(refund["creditNote"]["id"])

    summary = pos.cashier.get(f"/api/pos/shifts/{shift['id']}/cash-summary")

    assert summary["cashSales"] == 23
    assert summary["cashRefunds"] == 23
    assert summary["expectedBalance"] == 100


def test_a_result_applied_twice_changes_nothing(pos, kafka_on):
    sale = pos.invoiced_sale(quantity=2)
    refund = pos.refund(sale["id"], quantity=2)
    note_id = refund["creditNote"]["id"]

    pos.credit_note_result(note_id)
    pos.credit_note_result(note_id, number="001-001-999999999")

    shown = pos.manager.get(f"/api/pos/refunds/{refund['id']}")["creditNote"]
    assert shown["number"] == "001-001-000000012"


def test_a_rejected_credit_note_shows_why_and_can_be_asked_again(
    pos, kafka_on, db_session: Session
):
    sale = pos.invoiced_sale()
    refund = pos.refund(sale["id"])
    note_id = refund["creditNote"]["id"]

    pos.credit_note_result(note_id, "Rejected")

    shown = pos.manager.get(f"/api/pos/refunds/{refund['id']}")["creditNote"]
    assert (shown["status"], shown["rejectionReason"]) == ("REJECTED", "ERROR 68")

    again = pos.admin.post(f"/api/admin/credit-notes/{note_id}/request-again")

    assert (again["status"], again["rejectionReason"]) == ("PENDING", None)
    first, second = _credit_note_messages(db_session)
    assert first.event_id != second.event_id
    assert first.payload["payload"] == second.payload["payload"]

    pos.credit_note_result(note_id)
    error = pos.admin.error(
        "POST", f"/api/admin/credit-notes/{note_id}/request-again", 409
    )
    assert error["code"] == "CREDIT_NOTE_ALREADY_AUTHORIZED"


def test_a_viewer_cant_ask_again(pos, kafka_on, client, auth_headers):
    sale = pos.invoiced_sale()
    note_id = pos.refund(sale["id"])["creditNote"]["id"]
    viewer = Api(client, auth_headers(Role.VIEWER))

    viewer.error("POST", f"/api/admin/credit-notes/{note_id}/request-again", 403)


def test_the_invoice_of_a_cancelled_sale_is_credited_from_its_discrepancy(
    pos, kafka_on, db_session: Session
):
    sale = pos.sale(1, pos.customer)
    pos.invoice_result(sale["id"], "Rejected")
    pos.cashier.post(f"/api/pos/sales/{sale['id']}/cancel", {"reason": "Error"})
    pos.invoice_result(sale["id"])
    [discrepancy] = pos.admin.get(
        "/api/admin/invoice-discrepancies", params={"kind": "authorized_on_cancelled"}
    )
    assert discrepancy["creditNote"] is None
    path = f"/api/admin/invoice-discrepancies/{discrepancy['id']}/credit-note"

    note = pos.admin.post(path, {"reason": "Venta anulada"})

    assert (note["status"], note["refundId"], note["total"]) == ("PENDING", None, 11.5)
    assert note["invoiceId"] == INVOICE_ID
    [message] = _credit_note_messages(db_session)
    assert errors(SCHEMA, message.payload) == []
    assert (message.payload["payload"]["refund_id"]) is None
    assert message.payload["payload"]["total"] == "11.500000"
    [shown] = pos.admin.get(
        "/api/admin/invoice-discrepancies", params={"kind": "authorized_on_cancelled"}
    )
    assert shown["creditNote"]["id"] == note["id"]
    # Only one: the next one goes through asking again
    error = pos.admin.error("POST", path, 409, json={"reason": "Otra vez"})
    assert error["code"] == "CREDIT_NOTE_ALREADY_REQUESTED"

    pos.credit_note_result(note["id"])

    assert (
        pos.admin.get(
            "/api/admin/invoice-discrepancies",
            params={"kind": "authorized_on_cancelled"},
        )
        == []
    )
    shown_sale = pos.cashier.get(f"/api/pos/sales/{sale['id']}")
    assert (shown_sale["status"], shown_sale["invoiceStatus"]) == (
        "CANCELLED",
        "CREDITED",
    )
    assert shown_sale["invoiceId"] == INVOICE_ID


def test_the_invoice_of_a_cancelled_final_consumer_sale_stays_for_review(pos, kafka_on):
    sale = pos.sale(1)
    pos.invoice_result(sale["id"], "Rejected")
    pos.cashier.post(f"/api/pos/sales/{sale['id']}/cancel", {"reason": "Error"})
    pos.invoice_result(sale["id"])
    [discrepancy] = pos.admin.get(
        "/api/admin/invoice-discrepancies", params={"kind": "authorized_on_cancelled"}
    )
    assert discrepancy["sale"]["customerId"] is None

    error = pos.admin.error(
        "POST",
        f"/api/admin/invoice-discrepancies/{discrepancy['id']}/credit-note",
        409,
        json={"reason": "Venta anulada"},
    )

    assert error["code"] == "FINAL_CONSUMER_CREDIT_NOTE_NOT_ALLOWED"


def test_another_discrepancy_has_nothing_to_credit(pos, kafka_on, monkeypatch):
    from src.invoicing.infra.reconciliation import reconcile

    pos.sale(1, pos.customer)
    monkeypatch.setattr(config, "INVOICE_RECONCILIATION_PENDING_MINUTES", -60)
    reconcile()
    [discrepancy] = pos.admin.get("/api/admin/invoice-discrepancies")

    error = pos.admin.error(
        "POST",
        f"/api/admin/invoice-discrepancies/{discrepancy['id']}/credit-note",
        409,
        json={"reason": "Venta anulada"},
    )

    assert error["code"] == "CREDIT_NOTE_NOT_APPLICABLE"


def test_turning_it_off_stops_asking_and_keeps_what_is_there(
    pos, kafka_on, monkeypatch, db_session: Session
):
    sale = pos.invoiced_sale(quantity=2)
    issued = pos.refund(sale["id"])
    note_id = issued["creditNote"]["id"]

    monkeypatch.setattr(config, "CREDIT_NOTES_ENABLED", False)
    refund = pos.refund(sale["id"])

    assert refund["status"] == "COMPLETED"
    assert refund["creditNote"] is None
    assert len(_credit_note_messages(db_session)) == 1
    # What was asked keeps its state, and its late result still applies
    pos.credit_note_result(note_id)
    shown = pos.manager.get(f"/api/pos/refunds/{issued['id']}")["creditNote"]
    assert shown["status"] == "AUTHORIZED"
    # Asking by hand says why it can't
    pos.credit_note_result(note_id)
    assert (
        pos.admin.error(
            "POST", f"/api/admin/credit-notes/{note_id}/request-again", 409
        )["code"]
        == "CREDIT_NOTE_ALREADY_AUTHORIZED"
    )


def test_without_kafka_a_refund_asks_for_nothing(pos, db_session: Session):
    sale = pos.sale(1, pos.customer)

    refund = pos.refund(sale["id"])

    assert refund["creditNote"] is None
    assert _credit_note_messages(db_session) == []
