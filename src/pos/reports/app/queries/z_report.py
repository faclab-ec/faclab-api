from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session
from wireup import injectable

from src.pos.reports.app.queries.x_report import (
    get_shift,
    item_rows,
    method_rows,
    x_report,
)
from src.pos.shift.app.repositories import ShiftClosingRepository
from src.pos.shift.app.totals import ShiftTotalsReader
from src.pos.shift.domain.closing import MethodTotal, ShiftClosing
from src.shared.app.queries import Query, QueryHandler


@dataclass
class GetZReportQuery(Query):
    shift_id: int
    # The user's branches (None: all)
    branch_ids: frozenset[int] | None = None


def closing_report(closing: ShiftClosing) -> dict:
    """The Z report of a shift with its Z closing (S5.9): only what the closing
    kept when the shift closed, never recalculated"""
    cash = closing.cash_line
    return {
        "shift": {
            "id": closing.shift_id,
            "terminal_id": closing.terminal_id,
            "branch_id": closing.branch_id,
            "cashier_name": closing.cashier_name,
            "opened_at": closing.opened_at.isoformat() if closing.opened_at else None,
            "status": "CLOSED",
        },
        "sales_summary": {
            "count": closing.sales_count,
            "subtotal": closing.sales_subtotal,
            "tax": closing.sales_tax,
            "discount": closing.sales_discount,
            "total": closing.sales_total,
        },
        "payments_by_method": method_rows(
            [
                MethodTotal(
                    line.payment_method, line.payments_count, line.payments_total
                )
                for line in closing.lines
                if line.payments_count
            ]
        ),
        "customer_payments_by_method": method_rows(
            [
                MethodTotal(
                    line.payment_method,
                    line.customer_payments_count,
                    line.customer_payments_total,
                )
                for line in closing.lines
                if line.customer_payments_count
            ]
        ),
        "items_sold": item_rows(closing.items_sold),
        "refund_summary": {
            "count": closing.refunds_count,
            "total": closing.refunds_total,
        },
        "cash_reconciliation": {
            "opening_balance": closing.opening_balance,
            "cash_sales": closing.cash_sales,
            "cash_refunds": closing.cash_refunds,
            "customer_payments": closing.customer_payments,
            "cash_in": closing.cash_in,
            "cash_out": closing.cash_out,
            "expected_balance": cash.expected,
            "closing_balance": cash.counted,
            "discrepancy": cash.difference,
        },
        "closing": {
            "id": closing.id,
            "number": closing.number,
            "closed_at": closing.closed_at,
            "closed_by": closing.closed_by,
            "justification_threshold": closing.justification_threshold,
            "notes": closing.notes,
            "counts": [
                {
                    "payment_method": line.payment_method,
                    "expected": line.expected,
                    "counted": line.counted,
                    "difference": line.difference,
                    "justification": line.justification,
                }
                for line in closing.lines
                if line.countable
            ],
        },
    }


@injectable(lifetime="scoped")
class GetZReportQueryHandler(QueryHandler[GetZReportQuery, dict]):
    """The Z report: a shift closed with its Z closing (S5.9) answers what the
    closing kept; an open shift, or one closed before S5.9, is calculated from
    its data, without a closing"""

    def __init__(
        self,
        session: Session,
        totals: ShiftTotalsReader,
        closings: ShiftClosingRepository,
    ):
        self.session = session
        self.totals = totals
        self.closings = closings

    def _handle(self, query: GetZReportQuery) -> dict:
        shift = get_shift(self.session, query.shift_id, query.branch_ids)

        closing = self.closings.of_shift(shift.id)
        if closing is not None:
            return closing_report(closing)

        totals = self.totals.of_shift(shift.id)
        opening_balance = shift.opening_balance or Decimal("0")
        expected_balance = totals.expected_cash(opening_balance)
        closing_balance = shift.closing_balance
        discrepancy = (
            (closing_balance - expected_balance)
            if closing_balance is not None
            else None
        )
        return {
            **x_report(shift, totals),
            "refund_summary": {
                "count": totals.refunds_count,
                "total": totals.refunds_total,
            },
            "cash_reconciliation": {
                "opening_balance": opening_balance,
                **totals.cash_summary(),
                "expected_balance": expected_balance,
                "closing_balance": closing_balance,
                "discrepancy": discrepancy,
            },
            "closing": None,
        }
