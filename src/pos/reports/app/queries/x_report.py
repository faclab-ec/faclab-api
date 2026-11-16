from dataclasses import dataclass

from sqlalchemy.orm import Session
from wireup import injectable

from src.pos.shift.app.totals import ShiftTotalsReader
from src.pos.shift.domain.closing import ItemSold, MethodTotal, ShiftTotals
from src.pos.shift.infra.models import ShiftModel
from src.pos.terminal.app.scope import in_scope
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError
from src.shared.infra.tenant import tenant_criteria


def get_shift(
    session: Session, shift_id: int, branch_ids: frozenset[int] | None = None
) -> ShiftModel:
    """The context tenant's shift; another tenant's id, or a shift of a branch
    the user can't enter (`branch_ids`), is not found"""
    shift = (
        session.query(ShiftModel)
        .filter(ShiftModel.id == shift_id, *tenant_criteria(ShiftModel))
        .first()
    )
    if shift is None or not in_scope(shift.branch_id, branch_ids):
        raise NotFoundError(f"Shift with id {shift_id} not found")
    return shift


@dataclass
class GetXReportQuery(Query):
    shift_id: int
    # The user's branches (None: all)
    branch_ids: frozenset[int] | None = None


def method_rows(rows: list[MethodTotal]) -> list[dict]:
    return [
        {"payment_method": row.payment_method, "count": row.count, "total": row.total}
        for row in rows
    ]


def item_rows(items: list[ItemSold]) -> list[dict]:
    return [
        {
            "product_name": item.product_name,
            "sku": item.sku,
            "quantity": item.quantity,
            "total": item.total,
        }
        for item in items
    ]


def x_report(shift: ShiftModel, totals: ShiftTotals) -> dict:
    """What the shift moved so far, from its totals"""
    return {
        "shift": {
            "id": shift.id,
            "terminal_id": shift.terminal_id,
            "branch_id": shift.branch_id,
            "cashier_name": shift.cashier_name,
            "opened_at": shift.opened_at.isoformat() if shift.opened_at else None,
            "status": shift.status,
        },
        "sales_summary": {
            "count": totals.sales_count,
            "subtotal": totals.sales_subtotal,
            "tax": totals.sales_tax,
            "discount": totals.sales_discount,
            "total": totals.sales_total,
        },
        "payments_by_method": method_rows(totals.payments),
        # Payments on account taken in the shift (S5.5), by method
        "customer_payments_by_method": method_rows(totals.customer_payments),
        "items_sold": item_rows(totals.items_sold),
    }


@injectable(lifetime="scoped")
class GetXReportQueryHandler(QueryHandler[GetXReportQuery, dict]):
    def __init__(self, session: Session, totals: ShiftTotalsReader):
        self.session = session
        self.totals = totals

    def _handle(self, query: GetXReportQuery) -> dict:
        shift = get_shift(self.session, query.shift_id, query.branch_ids)
        return x_report(shift, self.totals.of_shift(shift.id))
