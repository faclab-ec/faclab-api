"""The portfolio's read models over SQLite: the aging adds up to what is owed,
the statement ends at what the customer owes, and a second tenant that reuses
the ids never shows up (S5.5)"""

from collections.abc import Iterator
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from src.customers.infra.models import CustomerModel
from src.pos.cash.app.queries.get_cash_summary import compute_cash_summary
from src.pos.cash.infra.models import CashMovementModel
from src.pos.refund.infra.models import RefundModel, RefundPaymentModel
from src.pos.shift.infra.models import ShiftModel
from src.receivables.app.queries.receivables import (
    GetCustomerAccountQuery,
    GetCustomerAccountQueryHandler,
    GetCustomerPaymentQuery,
    GetCustomerPaymentQueryHandler,
    GetCustomerStatementQuery,
    GetCustomerStatementQueryHandler,
    GetReceivableQuery,
    GetReceivableQueryHandler,
    GetReceivablesAgingQuery,
    GetReceivablesAgingQueryHandler,
    GetReceivablesQuery,
    GetReceivablesQueryHandler,
)
from src.receivables.infra.models import (
    CustomerPaymentModel,
    ReceivableApplicationModel,
    ReceivableModel,
)
from src.sales.infra.models import PaymentModel, SaleModel
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tenant import TenantContext, TenantSource, use_tenant
from src.tenancy.infra.models import TenantModel
from tests.sqlite import sqlite_session

OTHER = TenantContext(UUID("00000000-0000-4000-8000-0000000000c3"), TenantSource.TASK)
TODAY = date.today()
NOV = datetime(2026, 11, 1, 9)

_MODELS = (
    CustomerModel,
    ShiftModel,
    SaleModel,
    PaymentModel,
    RefundModel,
    RefundPaymentModel,
    CashMovementModel,
    ReceivableModel,
    CustomerPaymentModel,
    ReceivableApplicationModel,
)


def _receivable(
    session: Session,
    id: int,
    customer_id: int,
    amount: str,
    balance: str,
    due_in: int,
    created_at: datetime,
    status: str = "OPEN",
    cancelled_at: datetime | None = None,
) -> None:
    session.add(
        SaleModel(
            id=id,
            customer_id=customer_id,
            status="CONFIRMED",
            number=f"V-001-{id:06d}",
            total=Decimal(amount),
        )
    )
    session.flush()
    session.add(
        ReceivableModel(
            id=id,
            customer_id=customer_id,
            sale_id=id,
            amount=Decimal(amount),
            balance=Decimal(balance),
            issued_on=created_at.date(),
            due_on=TODAY + timedelta(days=due_in),
            term_days=30,
            status=status,
            cancelled_at=cancelled_at,
            created_at=created_at,
        )
    )


def _portfolio(session: Session) -> None:
    """Customer 1 owes 250 (150 overdue); customer 2 owes 380, all overdue"""
    session.add(CustomerModel(id=1, name="Andina", tax_id="1790012345001"))
    session.add(CustomerModel(id=2, name="Bloque", tax_id="1790012346001"))
    session.add(ShiftModel(id=1, cashier_name="Caja 1"))
    session.flush()
    _receivable(session, 1, 1, "100", "100", due_in=5, created_at=NOV.replace(day=8))
    _receivable(session, 2, 1, "200", "150", due_in=-10, created_at=NOV)
    _receivable(
        session,
        5,
        1,
        "40",
        "0",
        due_in=20,
        created_at=NOV.replace(day=2),
        status="CANCELLED",
        cancelled_at=NOV.replace(day=3),
    )
    _receivable(session, 3, 2, "300", "300", due_in=-45, created_at=NOV)
    _receivable(session, 4, 2, "50", "0", due_in=-45, created_at=NOV, status="PAID")
    _receivable(session, 6, 2, "80", "80", due_in=-100, created_at=NOV)
    session.flush()
    # 50 in cash at the shift, paid off receivable 2
    session.add(
        CustomerPaymentModel(
            id=1,
            number="AB-2026-0001",
            customer_id=1,
            amount=Decimal("50"),
            payment_method="CASH",
            paid_at=NOV.replace(day=5),
            shift_id=1,
        )
    )
    # By transfer at the same shift: not in its cash
    session.add(
        CustomerPaymentModel(
            id=2,
            number="AB-2026-0002",
            customer_id=2,
            amount=Decimal("50"),
            payment_method="TRANSFER",
            paid_at=NOV.replace(day=6),
            shift_id=1,
        )
    )
    session.flush()
    session.add(
        ReceivableApplicationModel(
            receivable_id=2,
            amount=Decimal("50"),
            kind="PAYMENT",
            customer_payment_id=1,
            applied_at=NOV.replace(day=5),
        )
    )
    session.add(
        ReceivableApplicationModel(
            receivable_id=4,
            amount=Decimal("50"),
            kind="PAYMENT",
            customer_payment_id=2,
            applied_at=NOV.replace(day=6),
        )
    )
    session.commit()


@pytest.fixture
def session() -> Iterator[Session]:
    db = sqlite_session(_MODELS)
    db.add(TenantModel(id=OTHER.tenant_id, ruc="0999999999001", legal_name="B"))
    db.commit()
    _portfolio(db)
    # Another tenant's portfolio, ten times bigger, with its own cash payment
    # at a shift
    with use_tenant(OTHER):
        db.add(CustomerModel(id=9, name="Otra", tax_id="0999999999001"))
        db.add(ShiftModel(id=9, cashier_name="Caja B"))
        db.flush()
        _receivable(db, 9, 9, "1000", "1000", due_in=-200, created_at=NOV)
        db.flush()
        db.add(
            CustomerPaymentModel(
                id=9,
                number="AB-2026-0001",
                customer_id=9,
                amount=Decimal("500"),
                payment_method="CASH",
                paid_at=NOV,
                shift_id=9,
            )
        )
        db.commit()
    yield db
    db.close()


def test_the_aging_adds_up_to_what_is_owed(session):
    aging = GetReceivablesAgingQueryHandler(session).handle(GetReceivablesAgingQuery())

    open_balances = sum(
        (
            r.balance
            for r in session.query(ReceivableModel).filter(
                ReceivableModel.status == "OPEN",
                ReceivableModel.tenant_id != OTHER.tenant_id,
            )
        ),
        Decimal("0"),
    )
    totals = aging["totals"]
    buckets = ("not_due", "days_1_30", "days_31_60", "days_61_90", "over_90")
    assert totals["total"] == open_balances == Decimal("630")
    assert sum(totals[b] for b in buckets) == totals["total"]
    assert {b: totals[b] for b in buckets} == {
        "not_due": Decimal("100"),
        "days_1_30": Decimal("150"),
        "days_31_60": Decimal("300"),
        "days_61_90": Decimal("0"),
        "over_90": Decimal("80"),
    }
    # Who owes the most first
    assert [
        (c["customer_id"], c["total"], c["receivables"]) for c in aging["customers"]
    ] == [
        (2, Decimal("380"), 2),
        (1, Decimal("250"), 2),
    ]
    for customer in aging["customers"]:
        assert sum(customer[b] for b in buckets) == customer["total"]


def test_the_list_shows_the_overdue_ones(session):
    handler = GetReceivablesQueryHandler(session)

    overdue = handler.handle(GetReceivablesQuery(overdue=True))
    of_customer = handler.handle(GetReceivablesQuery(customer_id=1, status="OPEN"))

    assert [r["id"] for r in overdue["items"]] == [6, 3, 2]
    assert overdue["items"][0]["days_overdue"] == 100
    assert overdue["items"][0]["sale_number"] == "V-001-000006"
    assert [r["id"] for r in of_customer["items"]] == [2, 1]
    assert of_customer["items"][1]["days_overdue"] == 0


def test_a_receivable_shows_what_lowered_it(session):
    detail = GetReceivableQueryHandler(session).handle(GetReceivableQuery(2))

    assert detail["balance"] == Decimal("150")
    assert [
        (a["kind"], a["amount"], a["document_number"]) for a in detail["applications"]
    ] == [("PAYMENT", Decimal("50"), "AB-2026-0001")]
    with pytest.raises(NotFoundError):
        GetReceivableQueryHandler(session).handle(GetReceivableQuery(99))


def test_the_account_of_a_customer(session):
    session.query(CustomerModel).filter(CustomerModel.id == 1).update(
        {"credit_limit": Decimal("1000"), "payment_terms": 30}
    )

    account = GetCustomerAccountQueryHandler(session).handle(
        GetCustomerAccountQuery(customer_id=1)
    )

    assert (account["outstanding"], account["overdue"], account["available"]) == (
        Decimal("250"),
        Decimal("150"),
        Decimal("750"),
    )
    assert account["has_credit"] is True
    assert [r["id"] for r in account["receivables"]] == [2, 1]


def test_the_statement_ends_at_what_the_customer_owes(session):
    statement = GetCustomerStatementQueryHandler(session).handle(
        GetCustomerStatementQuery(customer_id=1)
    )

    assert [(line["type"], line["balance"]) for line in statement["lines"]] == [
        ("SALE", Decimal("200")),
        ("SALE", Decimal("240")),
        ("CANCELLATION", Decimal("200")),
        ("PAYMENT", Decimal("150")),
        ("SALE", Decimal("250")),
    ]
    assert statement["opening_balance"] == Decimal("0")
    assert statement["closing_balance"] == Decimal("250")


def test_a_statement_of_a_period_starts_at_what_was_owed_before(session):
    statement = GetCustomerStatementQueryHandler(session).handle(
        GetCustomerStatementQuery(
            customer_id=1, from_date=date(2026, 11, 4), to_date=date(2026, 11, 5)
        )
    )

    assert statement["opening_balance"] == Decimal("200")
    assert [(line["type"], line["credit"]) for line in statement["lines"]] == [
        ("PAYMENT", Decimal("50"))
    ]
    assert statement["closing_balance"] == Decimal("150")


def test_a_payment_shows_what_it_paid(session):
    payment = GetCustomerPaymentQueryHandler(session).handle(GetCustomerPaymentQuery(1))

    assert payment["customer_name"] == "Andina"
    assert [(a["sale_number"], a["amount"]) for a in payment["applications"]] == [
        ("V-001-000002", Decimal("50"))
    ]


def test_cash_payments_on_account_count_in_the_shifts_cash(session):
    # The transfer doesn't
    assert compute_cash_summary(session, 1)["customer_payments"] == Decimal("50")
    # Nor another tenant's shift
    assert compute_cash_summary(session, 9)["customer_payments"] == 0


def test_another_tenants_portfolio_is_not_seen(session):
    aging = GetReceivablesAgingQueryHandler(session).handle(GetReceivablesAgingQuery())

    assert 9 not in {c["customer_id"] for c in aging["customers"]}
    with pytest.raises(NotFoundError):
        GetReceivableQueryHandler(session).handle(GetReceivableQuery(9))
    with pytest.raises(NotFoundError):
        GetCustomerAccountQueryHandler(session).handle(
            GetCustomerAccountQuery(customer_id=9)
        )
