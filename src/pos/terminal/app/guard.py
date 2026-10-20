from wireup import injectable

from src.pos.refund.app.repositories import RefundRepository
from src.pos.shift.app.repositories import ShiftRepository
from src.pos.terminal.app.resolver import TerminalRequest, TerminalResolver
from src.sales.app.repositories import SaleRepository
from src.shared.domain.exceptions import NotFoundError


@injectable(lifetime="scoped")
class PosBranchGuard:
    """The POS operates by id only on the request branch's sales, shifts and
    refunds: another branch's answers as one that doesn't exist. The routes
    call it before their handler, so the sale commands shared with the admin
    API stay as they are. Rows from before S2.6 have no branch and pass."""

    def __init__(
        self,
        resolver: TerminalResolver,
        sales: SaleRepository,
        shifts: ShiftRepository,
        refunds: RefundRepository,
    ):
        self.resolver = resolver
        self.sales = sales
        self.shifts = shifts
        self.refunds = refunds

    def sale(self, sale_id: int, request: TerminalRequest) -> None:
        sale = self.sales.get_by_id(sale_id)
        if sale is None or not self._in_branch(sale.branch_id, request):
            raise NotFoundError(f"Sale with id {sale_id} not found")

    def shift(self, shift_id: int, request: TerminalRequest) -> None:
        shift = self.shifts.get_by_id(shift_id)
        if shift is None or not self._in_branch(shift.branch_id, request):
            raise NotFoundError(f"Shift with id {shift_id} not found")

    def refund(self, refund_id: int, request: TerminalRequest) -> None:
        refund = self.refunds.get_by_id(refund_id)
        if refund is None or not self._in_branch(refund.branch_id, request):
            raise NotFoundError(f"Refund with id {refund_id} not found")

    def _in_branch(self, branch_id: int | None, request: TerminalRequest) -> bool:
        return branch_id is None or branch_id == self.resolver.branch_id(request)
