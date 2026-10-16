from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session
from wireup import injectable

from src.pos.cash.infra.models import CashMovementModel
from src.pos.refund.infra.models import RefundModel, RefundPaymentModel
from src.pos.shift.app.repositories import ShiftRepository
from src.sales.domain.entities import COMPLETED_SALE_STATUSES
from src.sales.infra.models import PaymentModel, SaleModel
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError
from src.shared.infra.tenant import tenant_criteria


def compute_cash_summary(session: Session, shift_id: int) -> dict:
    """Compute cash summary for a shift. Pure function reusable by CloseShift and reports.
    Only the context tenant's rows count."""

    # Cash sales: SUM of CASH payments from completed sales in this shift
    cash_sales = (
        session.query(func.coalesce(func.sum(PaymentModel.amount), Decimal("0")))
        .join(SaleModel, SaleModel.id == PaymentModel.sale_id)
        .filter(
            SaleModel.shift_id == shift_id, *tenant_criteria(PaymentModel, SaleModel)
        )
        .filter(SaleModel.status.in_(COMPLETED_SALE_STATUSES))
        .filter(PaymentModel.payment_method == "CASH")
        .scalar()
    )

    # Cash refunds: SUM of CASH refund payments from COMPLETED refunds in this shift
    cash_refunds = (
        session.query(func.coalesce(func.sum(RefundPaymentModel.amount), Decimal("0")))
        .join(RefundModel, RefundModel.id == RefundPaymentModel.refund_id)
        .filter(
            RefundModel.shift_id == shift_id,
            *tenant_criteria(RefundPaymentModel, RefundModel),
        )
        .filter(RefundModel.status == "COMPLETED")
        .filter(RefundPaymentModel.payment_method == "CASH")
        .scalar()
    )

    # Cash in: SUM of IN cash movements in this shift
    cash_in = (
        session.query(func.coalesce(func.sum(CashMovementModel.amount), Decimal("0")))
        .filter(
            CashMovementModel.shift_id == shift_id, *tenant_criteria(CashMovementModel)
        )
        .filter(CashMovementModel.type == "IN")
        .scalar()
    )

    # Cash out: SUM of OUT cash movements in this shift
    cash_out = (
        session.query(func.coalesce(func.sum(CashMovementModel.amount), Decimal("0")))
        .filter(
            CashMovementModel.shift_id == shift_id, *tenant_criteria(CashMovementModel)
        )
        .filter(CashMovementModel.type == "OUT")
        .scalar()
    )

    return {
        "cash_sales": cash_sales,
        "cash_refunds": cash_refunds,
        "cash_in": cash_in,
        "cash_out": cash_out,
    }


@dataclass
class GetCashSummaryQuery(Query):
    shift_id: int


@injectable(lifetime="scoped")
class GetCashSummaryQueryHandler(QueryHandler[GetCashSummaryQuery, dict]):
    def __init__(self, session: Session, shift_repo: ShiftRepository):
        self.session = session
        self.shift_repo = shift_repo

    def _handle(self, query: GetCashSummaryQuery) -> dict:
        shift = self.shift_repo.get_by_id(query.shift_id)
        if shift is None:
            raise NotFoundError(f"Shift with id {query.shift_id} not found")

        summary = compute_cash_summary(self.session, query.shift_id)

        opening_balance = shift.opening_balance
        expected_balance = (
            opening_balance
            + summary["cash_sales"]
            - summary["cash_refunds"]
            + summary["cash_in"]
            - summary["cash_out"]
        )

        return {
            "shift_id": query.shift_id,
            "opening_balance": opening_balance,
            **summary,
            "expected_balance": expected_balance,
        }
