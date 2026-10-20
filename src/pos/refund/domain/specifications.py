from typing import Any

from src.shared.domain.specifications import Specification


class RefundsOfSale(Specification):
    def __init__(self, sale_id: int):
        self.sale_id = sale_id

    def is_satisfied_by(self, candidate: Any) -> bool:
        return candidate.original_sale_id == self.sale_id

    def to_query_criteria(self) -> list[Any]:
        from src.pos.refund.infra.models import RefundModel

        return [RefundModel.original_sale_id == self.sale_id]


class RefundsByStatus(Specification):
    def __init__(self, status: str):
        self.status = str(status)

    def is_satisfied_by(self, candidate: Any) -> bool:
        return str(candidate.status) == self.status

    def to_query_criteria(self) -> list[Any]:
        from src.pos.refund.infra.models import RefundModel

        return [RefundModel.status == self.status]


class RefundsByTerminal(Specification):
    def __init__(self, terminal_id: int):
        self.terminal_id = terminal_id

    def is_satisfied_by(self, candidate: Any) -> bool:
        return candidate.terminal_id == self.terminal_id

    def to_query_criteria(self) -> list[Any]:
        from src.pos.refund.infra.models import RefundModel

        return [RefundModel.terminal_id == self.terminal_id]


class RefundsInBranches(Specification):
    """Refunds of these branches (from before S2.6, without branch, excluded)"""

    def __init__(self, branch_ids: frozenset[int]):
        self.branch_ids = branch_ids

    def is_satisfied_by(self, candidate: Any) -> bool:
        return candidate.branch_id in self.branch_ids

    def to_query_criteria(self) -> list[Any]:
        from src.pos.refund.infra.models import RefundModel

        return [RefundModel.branch_id.in_(self.branch_ids)]
