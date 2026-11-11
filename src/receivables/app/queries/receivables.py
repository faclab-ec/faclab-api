"""Cartera (S5.5): cuentas por cobrar, antigüedad de saldos, la cuenta de un
cliente y su estado de cuenta. Read models: consultan los modelos con el filtro
de la empresa (`tenant_criteria`) en cada tabla que leen."""

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func
from sqlalchemy.orm import Session
from wireup import injectable

from src.customers.infra.models import CustomerModel
from src.pos.refund.infra.models import RefundModel
from src.receivables.domain.allocation import AgingBucket, aging_bucket
from src.receivables.domain.entities import ReceivableApplicationKind, ReceivableStatus
from src.receivables.infra.models import (
    CustomerPaymentModel,
    ReceivableApplicationModel,
    ReceivableModel,
)
from src.sales.infra.models import SaleModel
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError
from src.shared.infra.tenant import tenant_criteria

ZERO = Decimal("0")


def receivable_row(
    model: ReceivableModel, sale_number: str | None, today: date
) -> dict[str, Any]:
    """Una cuenta como la muestran la cartera y la cuenta del cliente"""
    is_open = model.status == ReceivableStatus.OPEN.value
    return {
        "id": model.id,
        "customer_id": model.customer_id,
        "sale_id": model.sale_id,
        "sale_number": sale_number,
        "branch_id": model.branch_id,
        "amount": model.amount,
        "balance": model.balance,
        "issued_on": model.issued_on,
        "due_on": model.due_on,
        "term_days": model.term_days,
        "status": model.status,
        "cancelled_at": model.cancelled_at,
        # Only an open one is overdue
        "days_overdue": max((today - model.due_on).days, 0) if is_open else 0,
        "created_at": model.created_at,
    }


def _customer(session: Session, customer_id: int) -> CustomerModel:
    customer = (
        session.query(CustomerModel)
        .filter(CustomerModel.id == customer_id, *tenant_criteria(CustomerModel))
        .first()
    )
    if customer is None:
        raise NotFoundError(f"Customer with id {customer_id} not found")
    return customer


def _open_receivables(
    session: Session, customer_id: int
) -> list[tuple[ReceivableModel, str | None]]:
    return (
        session.query(ReceivableModel, SaleModel.number)
        .join(SaleModel, SaleModel.id == ReceivableModel.sale_id)
        .filter(
            ReceivableModel.customer_id == customer_id,
            ReceivableModel.status == ReceivableStatus.OPEN.value,
            *tenant_criteria(ReceivableModel, SaleModel),
        )
        .order_by(ReceivableModel.due_on, ReceivableModel.id)
        .tuples()
        .all()
    )


@dataclass
class GetReceivablesQuery(Query):
    customer_id: int | None = None
    status: str | None = None
    # Open and past their due date
    overdue: bool | None = None
    branch_id: int | None = None
    limit: int | None = 50
    offset: int | None = 0


@injectable(lifetime="scoped")
class GetReceivablesQueryHandler(QueryHandler[GetReceivablesQuery, dict]):
    """Las cuentas por cobrar, la que vence antes primero"""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetReceivablesQuery) -> dict:
        today = date.today()
        rows = (
            self.session.query(
                ReceivableModel,
                SaleModel.number,
                CustomerModel.name,
                CustomerModel.tax_id,
            )
            .join(SaleModel, SaleModel.id == ReceivableModel.sale_id)
            .join(CustomerModel, CustomerModel.id == ReceivableModel.customer_id)
            .filter(*tenant_criteria(ReceivableModel, SaleModel, CustomerModel))
        )
        if query.customer_id is not None:
            rows = rows.filter(ReceivableModel.customer_id == query.customer_id)
        if query.status is not None:
            rows = rows.filter(ReceivableModel.status == query.status)
        if query.branch_id is not None:
            rows = rows.filter(ReceivableModel.branch_id == query.branch_id)
        if query.overdue is not None:
            overdue = and_(
                ReceivableModel.status == ReceivableStatus.OPEN.value,
                ReceivableModel.due_on < today,
            )
            rows = rows.filter(overdue if query.overdue else ~overdue)
        total = rows.with_entities(func.count(ReceivableModel.id)).scalar()
        page = (
            rows.order_by(ReceivableModel.due_on, ReceivableModel.id)
            .limit(query.limit)
            .offset(query.offset)
            .all()
        )
        return {
            "items": [
                {
                    **receivable_row(model, number, today),
                    "customer_name": name,
                    "customer_tax_id": tax_id,
                }
                for model, number, name, tax_id in page
            ],
            "total": total,
            "limit": query.limit,
            "offset": query.offset,
        }


@dataclass
class GetReceivableQuery(Query):
    receivable_id: int


@injectable(lifetime="scoped")
class GetReceivableQueryHandler(QueryHandler[GetReceivableQuery, dict]):
    """Una cuenta con lo que bajó su saldo: abonos y devoluciones"""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetReceivableQuery) -> dict:
        row = (
            self.session.query(
                ReceivableModel,
                SaleModel.number,
                CustomerModel.name,
                CustomerModel.tax_id,
            )
            .join(SaleModel, SaleModel.id == ReceivableModel.sale_id)
            .join(CustomerModel, CustomerModel.id == ReceivableModel.customer_id)
            .filter(
                ReceivableModel.id == query.receivable_id,
                *tenant_criteria(ReceivableModel, SaleModel, CustomerModel),
            )
            .first()
        )
        if row is None:
            raise NotFoundError(f"Receivable with id {query.receivable_id} not found")
        model, number, name, tax_id = row
        applications = (
            self.session.query(
                ReceivableApplicationModel,
                CustomerPaymentModel.number,
                CustomerPaymentModel.payment_method,
                RefundModel.number,
            )
            .outerjoin(
                CustomerPaymentModel,
                and_(
                    CustomerPaymentModel.id
                    == ReceivableApplicationModel.customer_payment_id,
                    *tenant_criteria(CustomerPaymentModel),
                ),
            )
            .outerjoin(
                RefundModel,
                and_(
                    RefundModel.id == ReceivableApplicationModel.refund_id,
                    *tenant_criteria(RefundModel),
                ),
            )
            .filter(
                ReceivableApplicationModel.receivable_id == model.id,
                *tenant_criteria(ReceivableApplicationModel),
            )
            .order_by(
                ReceivableApplicationModel.applied_at, ReceivableApplicationModel.id
            )
            .all()
        )
        return {
            **receivable_row(model, number, date.today()),
            "customer_name": name,
            "customer_tax_id": tax_id,
            "applications": [
                {
                    "id": application.id,
                    "kind": application.kind,
                    "amount": application.amount,
                    "applied_at": application.applied_at,
                    "customer_payment_id": application.customer_payment_id,
                    "refund_id": application.refund_id,
                    # The payment's number, or the refund's
                    "document_number": payment_number or refund_number,
                    "payment_method": payment_method,
                }
                for application, payment_number, payment_method, refund_number in (
                    applications
                )
            ],
        }


def _bucket_totals() -> dict[str, Decimal]:
    return {bucket.value.lower(): ZERO for bucket in AgingBucket} | {"total": ZERO}


@dataclass
class GetReceivablesAgingQuery(Query):
    branch_id: int | None = None


@injectable(lifetime="scoped")
class GetReceivablesAgingQueryHandler(QueryHandler[GetReceivablesAgingQuery, dict]):
    """Antigüedad de saldos por cliente, en días de vencido a hoy: por vencer,
    1–30, 31–60, 61–90 y más de 90. Cada cuenta abierta cae en un solo tramo, así
    que los tramos suman lo que se debe."""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetReceivablesAgingQuery) -> dict:
        today = date.today()
        rows = (
            self.session.query(
                ReceivableModel.customer_id,
                CustomerModel.name,
                CustomerModel.tax_id,
                ReceivableModel.due_on,
                ReceivableModel.balance,
            )
            .join(CustomerModel, CustomerModel.id == ReceivableModel.customer_id)
            .filter(
                ReceivableModel.status == ReceivableStatus.OPEN.value,
                ReceivableModel.balance > 0,
                *tenant_criteria(ReceivableModel, CustomerModel),
            )
        )
        if query.branch_id is not None:
            rows = rows.filter(ReceivableModel.branch_id == query.branch_id)

        customers: dict[int, dict[str, Any]] = {}
        totals = _bucket_totals()
        for customer_id, name, tax_id, due_on, balance in rows.all():
            customer = customers.setdefault(
                customer_id,
                {
                    "customer_id": customer_id,
                    "customer_name": name,
                    "customer_tax_id": tax_id,
                    "receivables": 0,
                    **_bucket_totals(),
                },
            )
            bucket = aging_bucket((today - due_on).days).value.lower()
            customer[bucket] += balance
            customer["total"] += balance
            customer["receivables"] += 1
            totals[bucket] += balance
            totals["total"] += balance
        return {
            "as_of": today,
            "customers": sorted(
                customers.values(),
                key=lambda c: (-c["total"], c["customer_name"]),
            ),
            "totals": totals,
        }


@dataclass
class GetCustomerAccountQuery(Query):
    customer_id: int


@injectable(lifetime="scoped")
class GetCustomerAccountQueryHandler(QueryHandler[GetCustomerAccountQuery, dict]):
    """El crédito de un cliente: su cupo, lo que debe, lo vencido, lo que le
    queda disponible y sus cuentas abiertas (para abonar)"""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetCustomerAccountQuery) -> dict:
        today = date.today()
        customer = _customer(self.session, query.customer_id)
        receivables = [
            receivable_row(model, number, today)
            for model, number in _open_receivables(self.session, query.customer_id)
        ]
        outstanding = sum((r["balance"] for r in receivables), ZERO)
        overdue = sum(
            (r["balance"] for r in receivables if r["days_overdue"] > 0), ZERO
        )
        limit = customer.credit_limit
        has_credit = customer.is_active and limit is not None and limit > 0
        return {
            "customer_id": customer.id,
            "customer_name": customer.name,
            "customer_tax_id": customer.tax_id,
            "credit_limit": limit,
            "payment_terms": customer.payment_terms,
            "has_credit": has_credit,
            "outstanding": outstanding,
            "overdue": overdue,
            "available": max(limit - outstanding, ZERO)
            if has_credit and limit
            else ZERO,
            "receivables": receivables,
        }


# The order of a day's lines: the sale before what lowered its balance
_LINE_ORDER = {"SALE": 0, "PAYMENT": 1, "REFUND": 2, "CANCELLATION": 3}


@dataclass
class GetCustomerStatementQuery(Query):
    customer_id: int
    from_date: date | None = None
    to_date: date | None = None


@injectable(lifetime="scoped")
class GetCustomerStatementQueryHandler(QueryHandler[GetCustomerStatementQuery, dict]):
    """Estado de cuenta: el saldo al empezar el período, cada venta a crédito
    (cargo), abono, devolución acreditada y anulación (abonos a la cuenta) con el
    saldo después de cada una, y el saldo al terminar. Sin `to_date`, el saldo
    final es lo que el cliente debe hoy."""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetCustomerStatementQuery) -> dict:
        customer = _customer(self.session, query.customer_id)
        entries = sorted(
            self._entries(query.customer_id),
            key=lambda e: (e["date"], _LINE_ORDER[e["type"]], e["id"]),
        )
        start = datetime.combine(query.from_date, time.min) if query.from_date else None
        end = datetime.combine(query.to_date, time.max) if query.to_date else None

        opening = sum(
            (e["charge"] - e["credit"] for e in entries if start and e["date"] < start),
            ZERO,
        )
        balance = opening
        lines = []
        for entry in entries:
            if start and entry["date"] < start:
                continue
            if end and entry["date"] > end:
                break
            balance += entry["charge"] - entry["credit"]
            lines.append({**entry, "balance": balance})
        return {
            "customer_id": customer.id,
            "customer_name": customer.name,
            "customer_tax_id": customer.tax_id,
            "from_date": query.from_date,
            "to_date": query.to_date,
            "opening_balance": opening,
            "lines": lines,
            "closing_balance": balance,
        }

    def _entries(self, customer_id: int) -> list[dict[str, Any]]:
        entries = []
        receivables = (
            self.session.query(ReceivableModel, SaleModel.number)
            .join(SaleModel, SaleModel.id == ReceivableModel.sale_id)
            .filter(
                ReceivableModel.customer_id == customer_id,
                *tenant_criteria(ReceivableModel, SaleModel),
            )
            .all()
        )
        for receivable, number in receivables:
            entries.append(
                _line(
                    "SALE",
                    receivable.id,
                    receivable.created_at,
                    number,
                    charge=receivable.amount,
                    receivable_id=receivable.id,
                    sale_id=receivable.sale_id,
                    due_on=receivable.due_on,
                )
            )
            if receivable.status == ReceivableStatus.CANCELLED.value:
                entries.append(
                    _line(
                        "CANCELLATION",
                        receivable.id,
                        receivable.cancelled_at or receivable.created_at,
                        number,
                        credit=receivable.amount,
                        receivable_id=receivable.id,
                        sale_id=receivable.sale_id,
                    )
                )

        payments = (
            self.session.query(CustomerPaymentModel)
            .filter(
                CustomerPaymentModel.customer_id == customer_id,
                *tenant_criteria(CustomerPaymentModel),
            )
            .all()
        )
        for payment in payments:
            entries.append(
                _line(
                    "PAYMENT",
                    payment.id,
                    payment.paid_at,
                    payment.number,
                    credit=payment.amount,
                    customer_payment_id=payment.id,
                    payment_method=payment.payment_method,
                )
            )

        refunds = (
            self.session.query(ReceivableApplicationModel, RefundModel.number)
            .join(
                ReceivableModel,
                ReceivableModel.id == ReceivableApplicationModel.receivable_id,
            )
            .join(RefundModel, RefundModel.id == ReceivableApplicationModel.refund_id)
            .filter(
                ReceivableModel.customer_id == customer_id,
                ReceivableApplicationModel.kind
                == ReceivableApplicationKind.REFUND.value,
                *tenant_criteria(
                    ReceivableApplicationModel, ReceivableModel, RefundModel
                ),
            )
            .all()
        )
        for application, number in refunds:
            entries.append(
                _line(
                    "REFUND",
                    application.id,
                    application.applied_at,
                    number,
                    credit=application.amount,
                    receivable_id=application.receivable_id,
                    refund_id=application.refund_id,
                )
            )
        return entries


def _line(
    kind: str,
    id: int,
    when: datetime,
    document_number: str | None,
    *,
    charge: Decimal = ZERO,
    credit: Decimal = ZERO,
    **references: Any,
) -> dict[str, Any]:
    return {
        "type": kind,
        "id": id,
        "date": when,
        "document_number": document_number,
        "charge": charge,
        "credit": credit,
        "receivable_id": None,
        "sale_id": None,
        "customer_payment_id": None,
        "refund_id": None,
        "due_on": None,
        "payment_method": None,
        **references,
    }


@dataclass
class GetCustomerPaymentsQuery(Query):
    customer_id: int | None = None
    limit: int | None = 50
    offset: int | None = 0


@injectable(lifetime="scoped")
class GetCustomerPaymentsQueryHandler(QueryHandler[GetCustomerPaymentsQuery, dict]):
    """Los abonos, el último primero"""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetCustomerPaymentsQuery) -> dict:
        rows = (
            self.session.query(CustomerPaymentModel, CustomerModel.name)
            .join(CustomerModel, CustomerModel.id == CustomerPaymentModel.customer_id)
            .filter(*tenant_criteria(CustomerPaymentModel, CustomerModel))
        )
        if query.customer_id is not None:
            rows = rows.filter(CustomerPaymentModel.customer_id == query.customer_id)
        total = rows.with_entities(func.count(CustomerPaymentModel.id)).scalar()
        page = (
            rows.order_by(CustomerPaymentModel.id.desc())
            .limit(query.limit)
            .offset(query.offset)
            .all()
        )
        return {
            "items": [payment_row(model, name) for model, name in page],
            "total": total,
            "limit": query.limit,
            "offset": query.offset,
        }


def payment_row(model: CustomerPaymentModel, customer_name: str | None) -> dict:
    return {
        "id": model.id,
        "number": model.number,
        "customer_id": model.customer_id,
        "customer_name": customer_name,
        "amount": model.amount,
        "payment_method": model.payment_method,
        "reference": model.reference,
        "notes": model.notes,
        "paid_at": model.paid_at,
        "received_by": model.received_by,
        "branch_id": model.branch_id,
        "terminal_id": model.terminal_id,
        "shift_id": model.shift_id,
        "created_at": model.created_at,
    }


@dataclass
class GetCustomerPaymentQuery(Query):
    customer_payment_id: int


@injectable(lifetime="scoped")
class GetCustomerPaymentQueryHandler(QueryHandler[GetCustomerPaymentQuery, dict]):
    """Un abono y las cuentas a las que se aplicó"""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetCustomerPaymentQuery) -> dict:
        row = (
            self.session.query(CustomerPaymentModel, CustomerModel.name)
            .join(CustomerModel, CustomerModel.id == CustomerPaymentModel.customer_id)
            .filter(
                CustomerPaymentModel.id == query.customer_payment_id,
                *tenant_criteria(CustomerPaymentModel, CustomerModel),
            )
            .first()
        )
        if row is None:
            raise NotFoundError(
                f"Customer payment with id {query.customer_payment_id} not found"
            )
        model, name = row
        applications = (
            self.session.query(
                ReceivableApplicationModel,
                ReceivableModel.sale_id,
                ReceivableModel.balance,
                SaleModel.number,
            )
            .join(
                ReceivableModel,
                ReceivableModel.id == ReceivableApplicationModel.receivable_id,
            )
            .join(SaleModel, SaleModel.id == ReceivableModel.sale_id)
            .filter(
                ReceivableApplicationModel.customer_payment_id == model.id,
                *tenant_criteria(
                    ReceivableApplicationModel, ReceivableModel, SaleModel
                ),
            )
            .order_by(ReceivableApplicationModel.id)
            .all()
        )
        return {
            **payment_row(model, name),
            "applications": [
                {
                    "receivable_id": application.receivable_id,
                    "sale_id": sale_id,
                    "sale_number": number,
                    "amount": application.amount,
                    # The receivable's balance now
                    "balance": balance,
                }
                for application, sale_id, balance, number in applications
            ],
        }
