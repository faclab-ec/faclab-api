from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.pos.shift.app.repositories import ShiftRepository
from src.pos.shift.app.totals import ShiftTotalsReader
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class GetCashSummaryQuery(Query):
    shift_id: int
    # SHIFT_CLOSING_JUSTIFICATION_THRESHOLD, for the count screen (S5.9)
    justification_threshold: Decimal = Decimal("0")


@injectable(lifetime="scoped")
class GetCashSummaryQueryHandler(QueryHandler[GetCashSummaryQuery, dict]):
    """The shift's cash and what each payment method should have: the count
    screen shows it before closing (S5.9), from the same totals the closing
    keeps"""

    def __init__(self, shift_repo: ShiftRepository, totals: ShiftTotalsReader):
        self.shift_repo = shift_repo
        self.totals = totals

    def _handle(self, query: GetCashSummaryQuery) -> dict:
        shift = self.shift_repo.get_by_id(query.shift_id)
        if shift is None:
            raise NotFoundError(f"Shift with id {query.shift_id} not found")

        totals = self.totals.of_shift(query.shift_id)
        opening_balance = shift.opening_balance
        return {
            "shift_id": query.shift_id,
            "opening_balance": opening_balance,
            **totals.cash_summary(),
            "expected_balance": totals.expected_cash(opening_balance),
            # What to count: cash always, every other method the shift moved
            "by_method": [
                {
                    "payment_method": line.payment_method,
                    "payments_total": line.payments_total,
                    "customer_payments_total": line.customer_payments_total,
                    "refunds_total": line.refunds_total,
                    "expected": line.expected,
                }
                for line in totals.lines(opening_balance)
                if line.countable
            ],
            "justification_threshold": query.justification_threshold,
        }
