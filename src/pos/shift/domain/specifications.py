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


class ShiftsByTerminal(Specification):
    def __init__(self, terminal_id: int):
        self.terminal_id = terminal_id

    def is_satisfied_by(self, candidate: Any) -> bool:
        return candidate.terminal_id == self.terminal_id

    def to_query_criteria(self) -> list[Any]:
        from src.pos.shift.infra.models import ShiftModel

        return [ShiftModel.terminal_id == self.terminal_id]


class ShiftsInBranches(Specification):
    """Shifts of these branches (from before S2.6, without branch, excluded)"""

    def __init__(self, branch_ids: frozenset[int]):
        self.branch_ids = branch_ids

    def is_satisfied_by(self, candidate: Any) -> bool:
        return candidate.branch_id in self.branch_ids

    def to_query_criteria(self) -> list[Any]:
        from src.pos.shift.infra.models import ShiftModel

        return [ShiftModel.branch_id.in_(self.branch_ids)]
