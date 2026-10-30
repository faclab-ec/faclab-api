"""Reconciliation between sales and faclab-invoicing (S4.3), over SQLite with the
real repositories: which sales are overdue, opening without duplicates, resolving
when the condition goes away and reviewing."""

from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from src.invoicing.app.commands.discrepancies import (
    OpenInvoiceDiscrepancyCommand,
    OpenInvoiceDiscrepancyCommandHandler,
    ReconcileInvoicesCommand,
    ReconcileInvoicesCommandHandler,
    ResolveInvoiceDiscrepancyCommand,
    ResolveInvoiceDiscrepancyCommandHandler,
    ReviewInvoiceDiscrepancyCommand,
    ReviewInvoiceDiscrepancyCommandHandler,
)
from src.invoicing.app.queries.discrepancies import (
    ListInvoiceDiscrepanciesQuery,
    ListInvoiceDiscrepanciesQueryHandler,
)
from src.invoicing.domain.entities import (
    DiscrepancyKind,
    DiscrepancyStatus,
    InvoiceDiscrepancy,
)
from src.invoicing.domain.exceptions import DiscrepancyNotOpenError
from src.invoicing.infra.mappers import InvoiceDiscrepancyMapper
from src.invoicing.infra.models import InvoiceDiscrepancyModel
from src.invoicing.infra.repositories import SqlAlchemyInvoiceDiscrepancyRepository
from src.sales.domain.entities import InvoiceStatus, Sale, SaleStatus
from src.sales.domain.specifications import SalesAwaitingInvoice
from src.sales.infra.mappers import SaleMapper
from src.sales.infra.models import SaleModel
from src.sales.infra.repositories import SqlAlchemySaleRepository
from src.shared.app.audit import AuditAction
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tenant import TenantContext, TenantSource, use_tenant
from src.tenancy.infra.models import TenantModel
from tests.sqlite import sqlite_session

# A resend marks the sale pending from the real now
NOW = datetime.now()
CUTOFF = NOW - timedelta(minutes=30)
OLD = NOW - timedelta(hours=2)
RECENT = NOW - timedelta(minutes=5)
WITHOUT_RESULT = DiscrepancyKind.CONFIRMED_WITHOUT_RESULT


@pytest.fixture
def session(in_tenant) -> Iterator[Session]:
    db = sqlite_session([SaleModel, InvoiceDiscrepancyModel])
    yield db
    db.close()


@pytest.fixture
def sales(session) -> SqlAlchemySaleRepository:
    return SqlAlchemySaleRepository(session, SaleMapper())


@pytest.fixture
def discrepancies(session) -> SqlAlchemyInvoiceDiscrepancyRepository:
    return SqlAlchemyInvoiceDiscrepancyRepository(session, InvoiceDiscrepancyMapper())


@pytest.fixture
def reconcile(sales, discrepancies):
    handler = ReconcileInvoicesCommandHandler(sales, discrepancies)

    def run(batch_size: int = 500) -> dict:
        return handler.handle(
            ReconcileInvoicesCommand(older_than=CUTOFF, batch_size=batch_size)
        )

    return run


def _sale(sales, **fields) -> Sale:
    values: dict[str, Any] = {
        "status": SaleStatus.CONFIRMED,
        "emission_point_id": 1,
        "sale_date": OLD,
        "invoice_status": InvoiceStatus.PENDING,
        "invoice_requested_at": OLD,
        **fields,
    }
    return sales.create(Sale(**values))


def _unresolved(discrepancies, kind=WITHOUT_RESULT) -> list[InvoiceDiscrepancy]:
    return discrepancies.unresolved(kind)


# --- Entity -----------------------------------------------------------------


def test_only_an_open_discrepancy_is_reviewed():
    discrepancy = InvoiceDiscrepancy(id=1, sale_id=4, kind=WITHOUT_RESULT)

    discrepancy.review(7, "Ana Pérez", "Facturación la tiene pendiente")

    assert discrepancy.status == DiscrepancyStatus.REVIEWED
    assert (discrepancy.reviewed_by_id, discrepancy.reviewed_by_name) == (
        7,
        "Ana Pérez",
    )
    assert discrepancy.reviewed_at is not None
    with pytest.raises(DiscrepancyNotOpenError):
        discrepancy.review(7, "Ana Pérez")


def test_resolving_twice_keeps_the_first_time():
    discrepancy = InvoiceDiscrepancy(id=1, sale_id=4, kind=WITHOUT_RESULT)
    discrepancy.resolve()
    first = discrepancy.resolved_at

    discrepancy.resolve()

    assert discrepancy.status == DiscrepancyStatus.RESOLVED
    assert discrepancy.resolved_at == first


# --- Which sales are overdue --------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "overdue"),
    [
        ({}, True),
        # Never sent (Kafka off when it was confirmed): measured from its date
        ({"invoice_status": None, "invoice_requested_at": None}, True),
        ({"invoice_status": None, "sale_date": RECENT}, False),
        ({"invoice_requested_at": RECENT}, False),
        ({"invoice_status": InvoiceStatus.REJECTED}, False),
        ({"invoice_status": InvoiceStatus.AUTHORIZED}, False),
        ({"status": SaleStatus.INVOICED}, False),
        ({"status": SaleStatus.CANCELLED, "invoice_status": None}, False),
        ({"status": SaleStatus.DRAFT, "invoice_status": None}, False),
        # Before S2.6: it can't be invoiced
        ({"emission_point_id": None}, False),
    ],
)
def test_the_overdue_sales_are_the_same_in_sql_and_in_memory(sales, fields, overdue):
    sale = _sale(sales, **fields)
    spec = SalesAwaitingInvoice(CUTOFF)

    assert spec.is_satisfied_by(sale) is overdue
    assert [s.id for s in sales.filter_by_spec(spec)] == ([sale.id] if overdue else [])


# --- Reconcile ----------------------------------------------------------------


def test_a_pass_opens_one_per_overdue_sale_and_the_next_one_none(
    sales, discrepancies, reconcile
):
    pending = _sale(sales)
    never_sent = _sale(sales, invoice_status=None, invoice_requested_at=None)
    _sale(sales, invoice_requested_at=RECENT)
    _sale(sales, invoice_status=InvoiceStatus.REJECTED)

    assert reconcile() == {"opened": 2, "resolved": 0}
    assert reconcile() == {"opened": 0, "resolved": 0}

    opened = _unresolved(discrepancies)
    assert sorted(d.sale_id for d in opened) == [pending.id, never_sent.id]
    assert {d.status for d in opened} == {DiscrepancyStatus.OPEN}


def test_it_goes_through_every_batch(sales, discrepancies, reconcile):
    for _ in range(5):
        _sale(sales)

    assert reconcile(batch_size=2) == {"opened": 5, "resolved": 0}


def test_a_resent_sale_has_its_discrepancy_resolved(sales, discrepancies, reconcile):
    """The resend marks it pending again from now: no longer overdue"""
    sale = _sale(sales)
    reconcile()

    sale.await_invoice()
    sales.update(sale)

    assert reconcile() == {"opened": 0, "resolved": 1}
    assert _unresolved(discrepancies) == []


@pytest.mark.parametrize(
    "result",
    [
        {"status": SaleStatus.INVOICED, "invoice_status": InvoiceStatus.AUTHORIZED},
        {"invoice_status": InvoiceStatus.REJECTED},
        {"status": SaleStatus.CANCELLED},
    ],
)
def test_a_sale_with_a_result_or_cancelled_has_it_resolved(
    sales, discrepancies, reconcile, result
):
    sale = _sale(sales)
    reconcile()
    for name, value in result.items():
        setattr(sale, name, value)
    sales.update(sale)

    assert reconcile() == {"opened": 0, "resolved": 1}


def test_a_reviewed_discrepancy_is_not_opened_again_while_it_lasts(
    sales, discrepancies, reconcile
):
    sale = _sale(sales)
    reconcile()
    [discrepancy] = _unresolved(discrepancies)
    discrepancy.review(7, "Ana Pérez")
    discrepancies.update(discrepancy)

    assert reconcile() == {"opened": 0, "resolved": 0}

    sale.await_invoice()
    sales.update(sale)
    assert reconcile() == {"opened": 0, "resolved": 1}
    stored = discrepancies.get_by_id(discrepancy.require_id())
    assert stored is not None
    assert stored.status == DiscrepancyStatus.RESOLVED
    assert stored.reviewed_by_name == "Ana Pérez"


def test_a_sale_overdue_again_gets_a_new_discrepancy(sales, discrepancies, reconcile):
    sale = _sale(sales)
    reconcile()
    sale.await_invoice()
    sales.update(sale)
    reconcile()

    sale.invoice_requested_at = OLD
    sales.update(sale)

    assert reconcile() == {"opened": 1, "resolved": 0}
    assert discrepancies.count_by(sale_id=sale.id) == 2


def test_open_does_nothing_when_one_is_unresolved(sales, discrepancies):
    """Another worker opened it first"""
    sale = _sale(sales)

    assert discrepancies.open(sale.require_id(), WITHOUT_RESULT) is True
    assert discrepancies.open(sale.require_id(), WITHOUT_RESULT) is False
    # Another kind is another discrepancy
    assert discrepancies.open(
        sale.require_id(), DiscrepancyKind.AUTHORIZED_ON_CANCELLED, "inv-1"
    )


def test_each_tenant_reconciles_only_its_sales(session, sales, discrepancies):
    other = UUID("00000000-0000-4000-8000-00000000000b")
    session.add(TenantModel(id=other, ruc="1799999991001", legal_name="Otra"))
    session.commit()
    _sale(sales)
    handler = ReconcileInvoicesCommandHandler(sales, discrepancies)

    with use_tenant(TenantContext(other, TenantSource.TASK)):
        assert handler.handle(ReconcileInvoicesCommand(older_than=CUTOFF)) == {
            "opened": 0,
            "resolved": 0,
        }
        assert _unresolved(discrepancies) == []
    assert len(_unresolved(discrepancies)) == 0


# --- Results and resends ------------------------------------------------------


def test_the_resolve_command_closes_the_sales_discrepancy(
    sales, discrepancies, reconcile
):
    sale = _sale(sales)
    other = _sale(sales)
    reconcile()

    resolved = ResolveInvoiceDiscrepancyCommandHandler(discrepancies).handle(
        ResolveInvoiceDiscrepancyCommand(sale_id=sale.require_id())
    )

    assert resolved == 1
    assert [d.sale_id for d in _unresolved(discrepancies)] == [other.id]


def test_an_invoice_authorized_after_cancelling_opens_a_discrepancy(
    sales, discrepancies
):
    cancelled = _sale(sales, status=SaleStatus.CANCELLED, invoice_status=None)
    handler = OpenInvoiceDiscrepancyCommandHandler(sales, discrepancies)
    command = OpenInvoiceDiscrepancyCommand(
        sale_id=cancelled.require_id(), invoice_id="inv-1"
    )

    assert handler.handle(command) is True
    # The same message again opens nothing
    assert handler.handle(command) is False
    [discrepancy] = _unresolved(discrepancies, DiscrepancyKind.AUTHORIZED_ON_CANCELLED)
    assert discrepancy.invoice_id == "inv-1"


def test_only_a_cancelled_sale_gets_authorized_on_cancelled(sales, discrepancies):
    sale = _sale(sales)
    handler = OpenInvoiceDiscrepancyCommandHandler(sales, discrepancies)

    assert (
        handler.handle(
            OpenInvoiceDiscrepancyCommand(sale_id=sale.require_id(), invoice_id="i")
        )
        is False
    )
    with pytest.raises(NotFoundError):
        handler.handle(OpenInvoiceDiscrepancyCommand(sale_id=999, invoice_id="i"))


# --- Review -------------------------------------------------------------------


def test_reviewing_is_recorded_in_the_audit_log(sales, discrepancies, reconcile):
    sale = _sale(sales, branch_id=3)
    reconcile()
    [discrepancy] = _unresolved(discrepancies)
    audit = MagicMock()
    handler = ReviewInvoiceDiscrepancyCommandHandler(discrepancies, sales, audit)

    result = handler.handle(
        ReviewInvoiceDiscrepancyCommand(
            discrepancy_id=discrepancy.require_id(),
            user_id=7,
            user_name="Ana Pérez",
            note="El SRI está caído",
        )
    )

    assert result["status"] == DiscrepancyStatus.REVIEWED
    audit.record.assert_called_once_with(
        AuditAction.INVOICE_DISCREPANCY_REVIEWED,
        discrepancy.require_id(),
        before={"status": DiscrepancyStatus.OPEN},
        after={
            "status": DiscrepancyStatus.REVIEWED,
            "kind": WITHOUT_RESULT,
            "sale_id": sale.id,
            "note": "El SRI está caído",
        },
        branch_id=3,
    )
    with pytest.raises(DiscrepancyNotOpenError):
        handler.handle(
            ReviewInvoiceDiscrepancyCommand(discrepancy_id=discrepancy.require_id())
        )
    with pytest.raises(NotFoundError):
        handler.handle(ReviewInvoiceDiscrepancyCommand(discrepancy_id=999))


# --- List ---------------------------------------------------------------------


def test_the_list_shows_the_open_ones_with_their_sale(session, sales, reconcile):
    sale = _sale(sales, number="V-001-000007")
    reviewed = _sale(sales)
    reconcile()
    discrepancies = SqlAlchemyInvoiceDiscrepancyRepository(
        session, InvoiceDiscrepancyMapper()
    )
    [_, second] = _unresolved(discrepancies)
    second.review(7, "Ana Pérez")
    discrepancies.update(second)
    handler = ListInvoiceDiscrepanciesQueryHandler(session)

    result = handler.handle(ListInvoiceDiscrepanciesQuery())

    assert result["total"] == 1
    [item] = result["items"]
    assert (item["sale_id"], item["kind"], item["status"]) == (
        sale.id,
        "confirmed_without_result",
        "open",
    )
    assert item["sale"]["number"] == "V-001-000007"
    assert item["sale"]["invoice_status"] == "PENDING"
    assert (
        handler.handle(ListInvoiceDiscrepanciesQuery(status="reviewed"))["items"][0][
            "sale_id"
        ]
        == reviewed.id
    )
    assert handler.handle(ListInvoiceDiscrepanciesQuery(status=None))["total"] == 2


def test_the_list_only_shows_the_tenants_discrepancies(session, sales, reconcile):
    _sale(sales)
    reconcile()
    other = UUID("00000000-0000-4000-8000-00000000000b")
    session.add(TenantModel(id=other, ruc="1799999991001", legal_name="Otra"))
    session.commit()

    with use_tenant(TenantContext(other, TenantSource.TASK)):
        result = ListInvoiceDiscrepanciesQueryHandler(session).handle(
            ListInvoiceDiscrepanciesQuery()
        )

    assert result["total"] == 0
