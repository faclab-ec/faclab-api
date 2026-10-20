from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session
from wireup import injectable

from src.pos.cash.app.queries.get_cash_summary import compute_cash_summary
from src.pos.refund.infra.models import RefundModel
from src.pos.reports.app.queries.x_report import (
    GetXReportQuery,
    GetXReportQueryHandler,
    get_shift,
)
from src.shared.app.queries import Query, QueryHandler
from src.shared.infra.tenant import tenant_criteria


@dataclass
class GetZReportQuery(Query):
    shift_id: int
    # The user's branches (None: all)
    branch_ids: frozenset[int] | None = None


@injectable(lifetime="scoped")
class GetZReportQueryHandler(QueryHandler[GetZReportQuery, dict]):
    def __init__(self, session: Session, x_report_handler: GetXReportQueryHandler):
        self.session = session
        self.x_report_handler = x_report_handler

    def _handle(self, query: GetZReportQuery) -> dict:
        shift = get_shift(self.session, query.shift_id, query.branch_ids)

        # Get X-Report data
        x_data = self.x_report_handler._handle(
            GetXReportQuery(shift_id=query.shift_id, branch_ids=query.branch_ids)
        )

        # Refund summary
        refund_agg = (
            self.session.query(
                func.count(RefundModel.id).label("count"),
                func.coalesce(func.sum(RefundModel.total), Decimal("0")).label("total"),
            )
            .filter(
                RefundModel.shift_id == query.shift_id, *tenant_criteria(RefundModel)
            )
            .filter(RefundModel.status == "COMPLETED")
            .one()
        )

        # Cash reconciliation
        cash_summary = compute_cash_summary(self.session, query.shift_id)
        opening_balance = shift.opening_balance or Decimal("0")
        expected_balance = (
            opening_balance
            + cash_summary["cash_sales"]
            - cash_summary["cash_refunds"]
            + cash_summary["cash_in"]
            - cash_summary["cash_out"]
        )
        closing_balance = shift.closing_balance
        discrepancy = (
            (closing_balance - expected_balance)
            if closing_balance is not None
            else None
        )

        return {
            **x_data,
            "refund_summary": {
                "count": refund_agg.count,
                "total": refund_agg.total,
            },
            "cash_reconciliation": {
                "opening_balance": opening_balance,
                "cash_sales": cash_summary["cash_sales"],
                "cash_refunds": cash_summary["cash_refunds"],
                "cash_in": cash_summary["cash_in"],
                "cash_out": cash_summary["cash_out"],
                "expected_balance": expected_balance,
                "closing_balance": closing_balance,
                "discrepancy": discrepancy,
            },
        }
