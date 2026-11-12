"""Cuentas por pagar (S5.7): las cuentas, la de un proveedor y sus pagos. Read
models: consultan los modelos con el filtro de la empresa (`tenant_criteria`)
en cada tabla que leen."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func
from sqlalchemy.orm import Session
from wireup import injectable

from src.payables.domain.entities import PayableStatus
from src.payables.infra.models import (
    PayableApplicationModel,
    PayableModel,
    SupplierPaymentModel,
)
from src.purchasing.domain.entities import SupplierReturnStatus
from src.purchasing.infra.models import PurchaseOrderModel, SupplierReturnModel
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError
from src.shared.infra.tenant import tenant_criteria
from src.suppliers.infra.models import SupplierModel

ZERO = Decimal("0")
# The latest payments and returns the supplier's account shows
_RECENT = 20


def payable_row(
    model: PayableModel, order_number: str | None, today: date
) -> dict[str, Any]:
    """Una cuenta como la muestran la lista y la cuenta del proveedor"""
    is_open = model.status == PayableStatus.OPEN.value
    return {
        "id": model.id,
        "supplier_id": model.supplier_id,
        "purchase_order_id": model.purchase_order_id,
        "order_number": order_number,
        "purchase_receipt_id": model.purchase_receipt_id,
        "supplier_invoice_number": model.supplier_invoice_number,
        "amount": model.amount,
        "balance": model.balance,
        "issued_on": model.issued_on,
        "due_on": model.due_on,
        "term_days": model.term_days,
        "status": model.status,
        # Only an open one is overdue
        "days_overdue": max((today - model.due_on).days, 0) if is_open else 0,
        "created_at": model.created_at,
    }


def payment_row(model: SupplierPaymentModel, supplier_name: str | None) -> dict:
    return {
        "id": model.id,
        "number": model.number,
        "supplier_id": model.supplier_id,
        "supplier_name": supplier_name,
        "amount": model.amount,
        "payment_method": model.payment_method,
        "reference": model.reference,
        "notes": model.notes,
        "paid_at": model.paid_at,
        "paid_by": model.paid_by,
        "created_at": model.created_at,
    }


def _supplier(session: Session, supplier_id: int) -> SupplierModel:
    supplier = (
        session.query(SupplierModel)
        .filter(SupplierModel.id == supplier_id, *tenant_criteria(SupplierModel))
        .first()
    )
    if supplier is None:
        raise NotFoundError(f"Supplier with id {supplier_id} not found")
    return supplier


@dataclass
class GetPayablesQuery(Query):
    supplier_id: int | None = None
    status: str | None = None
    purchase_order_id: int | None = None
    # Open and past their due date
    overdue: bool | None = None
    limit: int | None = 50
    offset: int | None = 0


@injectable(lifetime="scoped")
class GetPayablesQueryHandler(QueryHandler[GetPayablesQuery, dict]):
    """Las cuentas por pagar, la que vence antes primero"""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetPayablesQuery) -> dict:
        today = date.today()
        rows = (
            self.session.query(
                PayableModel,
                PurchaseOrderModel.order_number,
                SupplierModel.name,
                SupplierModel.tax_id,
            )
            .join(
                PurchaseOrderModel,
                PurchaseOrderModel.id == PayableModel.purchase_order_id,
            )
            .join(SupplierModel, SupplierModel.id == PayableModel.supplier_id)
            .filter(*tenant_criteria(PayableModel, PurchaseOrderModel, SupplierModel))
        )
        if query.supplier_id is not None:
            rows = rows.filter(PayableModel.supplier_id == query.supplier_id)
        if query.status is not None:
            rows = rows.filter(PayableModel.status == query.status)
        if query.purchase_order_id is not None:
            rows = rows.filter(
                PayableModel.purchase_order_id == query.purchase_order_id
            )
        if query.overdue is not None:
            overdue = and_(
                PayableModel.status == PayableStatus.OPEN.value,
                PayableModel.due_on < today,
            )
            rows = rows.filter(overdue if query.overdue else ~overdue)
        total = rows.with_entities(func.count(PayableModel.id)).scalar()
        page = (
            rows.order_by(PayableModel.due_on, PayableModel.id)
            .limit(query.limit)
            .offset(query.offset)
            .all()
        )
        return {
            "items": [
                {
                    **payable_row(model, number, today),
                    "supplier_name": name,
                    "supplier_tax_id": tax_id,
                }
                for model, number, name, tax_id in page
            ],
            "total": total,
            "limit": query.limit,
            "offset": query.offset,
        }


@dataclass
class GetPayableQuery(Query):
    payable_id: int


@injectable(lifetime="scoped")
class GetPayableQueryHandler(QueryHandler[GetPayableQuery, dict]):
    """Una cuenta con lo que bajó su saldo: pagos y devoluciones"""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetPayableQuery) -> dict:
        row = (
            self.session.query(
                PayableModel,
                PurchaseOrderModel.order_number,
                SupplierModel.name,
                SupplierModel.tax_id,
            )
            .join(
                PurchaseOrderModel,
                PurchaseOrderModel.id == PayableModel.purchase_order_id,
            )
            .join(SupplierModel, SupplierModel.id == PayableModel.supplier_id)
            .filter(
                PayableModel.id == query.payable_id,
                *tenant_criteria(PayableModel, PurchaseOrderModel, SupplierModel),
            )
            .first()
        )
        if row is None:
            raise NotFoundError(f"Payable with id {query.payable_id} not found")
        model, number, name, tax_id = row
        applications = (
            self.session.query(
                PayableApplicationModel,
                SupplierPaymentModel.number,
                SupplierPaymentModel.payment_method,
                SupplierReturnModel.number,
            )
            .outerjoin(
                SupplierPaymentModel,
                and_(
                    SupplierPaymentModel.id
                    == PayableApplicationModel.supplier_payment_id,
                    *tenant_criteria(SupplierPaymentModel),
                ),
            )
            .outerjoin(
                SupplierReturnModel,
                and_(
                    SupplierReturnModel.id
                    == PayableApplicationModel.supplier_return_id,
                    *tenant_criteria(SupplierReturnModel),
                ),
            )
            .filter(
                PayableApplicationModel.payable_id == model.id,
                *tenant_criteria(PayableApplicationModel),
            )
            .order_by(PayableApplicationModel.applied_at, PayableApplicationModel.id)
            .all()
        )
        return {
            **payable_row(model, number, date.today()),
            "supplier_name": name,
            "supplier_tax_id": tax_id,
            "applications": [
                {
                    "id": application.id,
                    "kind": application.kind,
                    "amount": application.amount,
                    "applied_at": application.applied_at,
                    "supplier_payment_id": application.supplier_payment_id,
                    "supplier_return_id": application.supplier_return_id,
                    # The payment's number, or the return's
                    "document_number": payment_number or return_number,
                    "payment_method": payment_method,
                }
                for application, payment_number, payment_method, return_number in (
                    applications
                )
            ],
        }


@dataclass
class GetSupplierAccountQuery(Query):
    supplier_id: int


@injectable(lifetime="scoped")
class GetSupplierAccountQueryHandler(QueryHandler[GetSupplierAccountQuery, dict]):
    """Lo que se le debe a un proveedor: el saldo, lo vencido, sus cuentas
    abiertas (para pagar), sus últimos pagos y sus devoluciones confirmadas
    con lo que acreditaron y lo que debe reembolsar"""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetSupplierAccountQuery) -> dict:
        today = date.today()
        supplier = _supplier(self.session, query.supplier_id)
        payables = [
            payable_row(model, number, today)
            for model, number in (
                self.session.query(PayableModel, PurchaseOrderModel.order_number)
                .join(
                    PurchaseOrderModel,
                    PurchaseOrderModel.id == PayableModel.purchase_order_id,
                )
                .filter(
                    PayableModel.supplier_id == query.supplier_id,
                    PayableModel.status == PayableStatus.OPEN.value,
                    *tenant_criteria(PayableModel, PurchaseOrderModel),
                )
                .order_by(PayableModel.due_on, PayableModel.id)
                .tuples()
                .all()
            )
        ]
        payments = (
            self.session.query(SupplierPaymentModel)
            .filter(
                SupplierPaymentModel.supplier_id == query.supplier_id,
                *tenant_criteria(SupplierPaymentModel),
            )
            .order_by(SupplierPaymentModel.id.desc())
            .limit(_RECENT)
            .all()
        )
        returns = (
            self.session.query(SupplierReturnModel, PurchaseOrderModel.order_number)
            .join(
                PurchaseOrderModel,
                PurchaseOrderModel.id == SupplierReturnModel.purchase_order_id,
            )
            .filter(
                SupplierReturnModel.supplier_id == query.supplier_id,
                SupplierReturnModel.status == SupplierReturnStatus.CONFIRMED.value,
                *tenant_criteria(SupplierReturnModel, PurchaseOrderModel),
            )
            .order_by(SupplierReturnModel.id.desc())
            .limit(_RECENT)
            .all()
        )
        outstanding = sum((p["balance"] for p in payables), ZERO)
        overdue = sum((p["balance"] for p in payables if p["days_overdue"] > 0), ZERO)
        return {
            "supplier_id": supplier.id,
            "supplier_name": supplier.name,
            "supplier_tax_id": supplier.tax_id,
            "payment_terms": supplier.payment_terms,
            "outstanding": outstanding,
            "overdue": overdue,
            "payables": payables,
            "payments": [payment_row(model, supplier.name) for model in payments],
            "returns": [
                {
                    "id": model.id,
                    "number": model.number,
                    "purchase_order_id": model.purchase_order_id,
                    "order_number": order_number,
                    "supplier_credit_note_number": model.supplier_credit_note_number,
                    "total": model.total,
                    "credited_amount": model.credited_amount,
                    "refund_due": model.total - model.credited_amount,
                    "confirmed_at": model.confirmed_at,
                }
                for model, order_number in returns
            ],
        }


@dataclass
class GetSupplierPaymentsQuery(Query):
    supplier_id: int | None = None
    limit: int | None = 50
    offset: int | None = 0


@injectable(lifetime="scoped")
class GetSupplierPaymentsQueryHandler(QueryHandler[GetSupplierPaymentsQuery, dict]):
    """Los pagos a proveedores, el último primero"""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetSupplierPaymentsQuery) -> dict:
        rows = (
            self.session.query(SupplierPaymentModel, SupplierModel.name)
            .join(SupplierModel, SupplierModel.id == SupplierPaymentModel.supplier_id)
            .filter(*tenant_criteria(SupplierPaymentModel, SupplierModel))
        )
        if query.supplier_id is not None:
            rows = rows.filter(SupplierPaymentModel.supplier_id == query.supplier_id)
        total = rows.with_entities(func.count(SupplierPaymentModel.id)).scalar()
        page = (
            rows.order_by(SupplierPaymentModel.id.desc())
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


@dataclass
class GetSupplierPaymentQuery(Query):
    supplier_payment_id: int


@injectable(lifetime="scoped")
class GetSupplierPaymentQueryHandler(QueryHandler[GetSupplierPaymentQuery, dict]):
    """Un pago y las cuentas a las que se aplicó"""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetSupplierPaymentQuery) -> dict:
        row = (
            self.session.query(SupplierPaymentModel, SupplierModel.name)
            .join(SupplierModel, SupplierModel.id == SupplierPaymentModel.supplier_id)
            .filter(
                SupplierPaymentModel.id == query.supplier_payment_id,
                *tenant_criteria(SupplierPaymentModel, SupplierModel),
            )
            .first()
        )
        if row is None:
            raise NotFoundError(
                f"Supplier payment with id {query.supplier_payment_id} not found"
            )
        model, name = row
        applications = (
            self.session.query(
                PayableApplicationModel,
                PayableModel.purchase_order_id,
                PayableModel.supplier_invoice_number,
                PayableModel.balance,
            )
            .join(PayableModel, PayableModel.id == PayableApplicationModel.payable_id)
            .filter(
                PayableApplicationModel.supplier_payment_id == model.id,
                *tenant_criteria(PayableApplicationModel, PayableModel),
            )
            .order_by(PayableApplicationModel.id)
            .all()
        )
        return {
            **payment_row(model, name),
            "applications": [
                {
                    "payable_id": application.payable_id,
                    "purchase_order_id": purchase_order_id,
                    "supplier_invoice_number": invoice_number,
                    "amount": application.amount,
                    # The payable's balance now
                    "balance": balance,
                }
                for application, purchase_order_id, invoice_number, balance in (
                    applications
                )
            ],
        }
