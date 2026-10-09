from typing import Any

from src.shared.domain.specifications import Specification


class ShiftsByStatus(Specification):
    def __init__(self, status: str):
        self.status = str(status)

    def is_satisfied_by(self, candidate: Any) -> bool:
        return str(candidate.status) == self.status

    def to_query_criteria(self) -> list[Any]:
        from src.pos.shift.infra.models import ShiftModel

        return [ShiftModel.status == self.status]
