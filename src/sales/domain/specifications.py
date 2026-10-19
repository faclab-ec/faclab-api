"""Especificaciones del dominio de Sales"""

from typing import Any

from src.shared.domain.specifications import Specification


class ParkedSalesSpecification(Specification):
    """Especificacion para ventas aparcadas (DRAFT con parked_at no nulo)"""

    def is_satisfied_by(self, candidate: Any) -> bool:
        return candidate.status == "DRAFT" and candidate.parked_at is not None

    def to_query_criteria(self) -> list[Any]:
        from src.sales.infra.models import SaleModel

        return [
            SaleModel.status == "DRAFT",
            SaleModel.parked_at.isnot(None),
        ]


class SalesByTerminal(Specification):
    """Ventas de una terminal del POS"""

    def __init__(self, terminal_id: int):
        self.terminal_id = terminal_id

    def is_satisfied_by(self, candidate: Any) -> bool:
        return candidate.terminal_id == self.terminal_id

    def to_query_criteria(self) -> list[Any]:
        from src.sales.infra.models import SaleModel

        return [SaleModel.terminal_id == self.terminal_id]
