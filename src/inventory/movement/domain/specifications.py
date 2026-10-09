from datetime import datetime
from typing import Any

from src.inventory.movement.domain.constants import MovementType
from src.shared.domain.specifications import Specification


class MovementsByProduct(Specification):
    def __init__(self, product_id: int):
        self.product_id = product_id

    def is_satisfied_by(self, candidate: Any) -> bool:
        return candidate.product_id == self.product_id

    def to_query_criteria(self) -> list[Any]:
        from src.inventory.movement.infra.models import MovementModel

        return [MovementModel.product_id == self.product_id]


class MovementsByType(Specification):
    def __init__(self, movement_type: MovementType | str):
        self.movement_type = MovementType(movement_type)

    def is_satisfied_by(self, candidate: Any) -> bool:
        return candidate.type == self.movement_type

    def to_query_criteria(self) -> list[Any]:
        from src.inventory.movement.infra.models import MovementModel

        return [MovementModel.type == self.movement_type]


class MovementsInDateRange(Specification):
    """Movimientos con fecha entre `from_date` y `to_date`, ambos incluidos; un
    extremo en None no limita"""

    def __init__(self, from_date: datetime | None, to_date: datetime | None):
        self.from_date = from_date
        self.to_date = to_date

    def is_satisfied_by(self, candidate: Any) -> bool:
        if candidate.date is None:
            return False
        if self.from_date is not None and candidate.date < self.from_date:
            return False
        return self.to_date is None or candidate.date <= self.to_date

    def to_query_criteria(self) -> list[Any]:
        from src.inventory.movement.infra.models import MovementModel

        criteria = []
        if self.from_date is not None:
            criteria.append(MovementModel.date >= self.from_date)
        if self.to_date is not None:
            criteria.append(MovementModel.date <= self.to_date)
        return criteria
