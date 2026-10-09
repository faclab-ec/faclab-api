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
