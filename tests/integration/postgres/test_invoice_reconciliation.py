"""Reconciliation with faclab-invoicing (S4.3) against PostgreSQL: a sale whose
`sales.confirmed` never left the outbox shows up as a discrepancy of its tenant
only, the resend resolves it and the invoice it brings closes the loop; an
invoice authorized after the sale was cancelled shows up too. The task runs as
in the worker: tenants found as faclab_worker, each one reconciled as faclab_app
under row-level security."""

from uuid import UUID

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from config import config
from src.auth.domain.entities import Role
from src.invoicing.infra.invoice_messages import handle_invoice_message
from src.invoicing.infra.reconciliation import reconcile
from src.shared.domain.tenant import TenantContext, TenantSource
from src.shared.infra.outbox.models import OutboxMessageModel
from src.shared.infra.tenant import tenant_scope
from tests.integration.postgres.api import (
    Api,
    at_terminal,
    make_location,
    make_movement,
    make_product,
    make_terminal,
    make_warehouse,
)
from tests.integration.postgres.tenants import OTHER_TENANT_RUC, ensure_tenant

DISCREPANCIES = "/api/admin/invoice-discrepancies"


@pytest.fixture
def kafka_on(monkeypatch) -> None:
    monkeypatch.setattr(config, "KAFKA_ENABLED", True)


@pytest.fixture
def admin_api(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def pos(client, admin_api, auth_headers) -> tuple[Api, int]:
    """A cashier with an open shift at a terminal whose location has stock of
    a product"""
    location = make_location(admin_api, make_warehouse(admin_api)["id"])
    product = make_product(admin_api, "SKU-1", salePrice="10.00")
    make_movement(admin_api, product["id"], 10, location["id"])
    terminal = make_terminal(admin_api, location["id"])
    cashier = Api(client, at_terminal(auth_headers(Role.CASHIER), terminal))
    cashier.post("/api/pos/shifts/open", {"openingBalance": "0"})
    return cashier, product["id"]


@pytest.fixture
def cashier(pos) -> Api:
    return pos[0]


def _sell(pos: tuple[Api, int]) -> dict:
    cashier, product_id = pos
    return cashier.post(
        "/api/pos/sales/quick",
        {
            "items": [{"productId": product_id, "quantity": 1}],
            "payments": [{"amount": "11.50", "paymentMethod": "CASH"}],
        },
    )


def _waiting_for_two_hours(engine: Engine, sale_id: int) -> None:
    """As the superuser: the sale was sent two hours ago"""
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE sales SET invoice_requested_at = now() - interval '2 hours' "
                "WHERE id = :id"
            ),
            {"id": sale_id},
        )


def _handle(message: dict, tenant_id: UUID) -> None:
    """As the consumer does: in the tenant of its `faclab-tenant-id` header"""
    with tenant_scope(TenantContext(tenant_id, TenantSource.MESSAGE)):
        handle_invoice_message(message)


def _authorized(sale_id: int, invoice_id: str) -> dict:
    return {
        "type": "InvoiceAuthorized",
        "invoiceId": invoice_id,
        "saleId": str(sale_id),
        "status": "authorized",
        "occurredAt": "2026-10-29T15:00:00.000Z",
    }


def test_a_sale_whose_message_was_lost_is_found_and_resent(
    kafka_on,
    pos,
    cashier,
    admin_api,
    client,
    auth_headers,
    pg_engine,
    db_session: Session,
    tenant,
):
    sale = _sell(pos)
    assert sale["invoiceStatus"] == "PENDING"
    # Its message never reaches faclab-invoicing
    with pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM outbox_messages"))
    _waiting_for_two_hours(pg_engine, sale["id"])
    other_tenant = ensure_tenant(pg_engine, OTHER_TENANT_RUC)
    other_admin = Api(
        client, auth_headers(Role.ADMIN, tenant_id=other_tenant, username="other")
    )

    assert reconcile() == {"opened": 1, "resolved": 0}

    [listed] = admin_api.get(DISCREPANCIES)
    assert (listed["saleId"], listed["kind"], listed["status"]) == (
        sale["id"],
        "confirmed_without_result",
        "open",
    )
    assert (listed["sale"]["number"], listed["sale"]["invoiceStatus"]) == (
        sale["number"],
        "PENDING",
    )
    # Only its tenant sees it
    assert other_admin.get(DISCREPANCIES) == []
    # A second pass opens nothing new
    assert reconcile() == {"opened": 0, "resolved": 0}

    resent = admin_api.post(f"/api/admin/sales/{sale['id']}/request-invoice")

    assert resent["invoiceStatus"] == "PENDING"
    [message] = db_session.scalars(select(OutboxMessageModel))
    assert (message.topic, message.payload["payload"]["sale_id"]) == (
        "sales.confirmed",
        sale["id"],
    )
    # Resolved in the resend's transaction, without waiting for the task
    assert admin_api.get(DISCREPANCIES) == []
    [resolved] = admin_api.get(DISCREPANCIES, params={"status": "resolved"})
    assert resolved["id"] == listed["id"]
    assert resolved["resolvedAt"] is not None

    # faclab-invoicing authorizes the invoice of the resend
    _handle(_authorized(sale["id"], "9c5cc2d1-invoice"), tenant)

    assert reconcile() == {"opened": 0, "resolved": 0}
    shown = cashier.get(f"/api/pos/sales/{sale['id']}")
    assert (shown["status"], shown["invoiceStatus"]) == ("INVOICED", "AUTHORIZED")


def test_an_invoice_authorized_after_cancelling_is_a_discrepancy(
    kafka_on, pos, cashier, admin_api, tenant
):
    sale = _sell(pos)
    _handle(
        {
            **_authorized(sale["id"], "inv-1"),
            "type": "InvoiceRejected",
            "status": "rejected",
            "reason": "IDENTIFICACION INVALIDA",
        },
        tenant,
    )
    cashier.post(f"/api/pos/sales/{sale['id']}/cancel")

    # A second invoice the SRI authorized anyway
    _handle(_authorized(sale["id"], "inv-2"), tenant)
    _handle(_authorized(sale["id"], "inv-2"), tenant)

    [listed] = admin_api.get(DISCREPANCIES)
    assert (listed["kind"], listed["invoiceId"], listed["sale"]["status"]) == (
        "authorized_on_cancelled",
        "inv-2",
        "CANCELLED",
    )


def test_a_reviewed_discrepancy_leaves_the_open_list(
    kafka_on, pos, admin_api, client, auth_headers, pg_engine
):
    sale = _sell(pos)
    _waiting_for_two_hours(pg_engine, sale["id"])
    reconcile()
    [listed] = admin_api.get(DISCREPANCIES)
    manager = Api(
        client, auth_headers(Role.MANAGER, full_name="Gerente Uno", username="gerente")
    )

    reviewed = manager.post(
        f"{DISCREPANCIES}/{listed['id']}/review", {"note": "El SRI está caído"}
    )

    assert (reviewed["status"], reviewed["reviewedByName"], reviewed["reviewNote"]) == (
        "reviewed",
        "Gerente Uno",
        "El SRI está caído",
    )
    assert admin_api.get(DISCREPANCIES) == []
    # Still overdue, but not opened again
    assert reconcile() == {"opened": 0, "resolved": 0}
    error = manager.error(
        "POST", f"{DISCREPANCIES}/{listed['id']}/review", 409, json={}
    )
    assert error["code"] == "INVOICE_DISCREPANCY_NOT_OPEN"
    # A viewer can read but not review
    viewer = Api(client, auth_headers(Role.VIEWER, username="viewer"))
    assert (
        viewer.get(DISCREPANCIES, params={"status": "reviewed"})[0]["id"]
        == listed["id"]
    )
    viewer.error("POST", f"{DISCREPANCIES}/{listed['id']}/review", 403, json={})
