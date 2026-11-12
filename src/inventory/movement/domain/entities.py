from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.shared.domain.entities import Entity
from src.shared.domain.exceptions import InvalidValueError

from .constants import MovementType
from .exceptions import InvalidMovementTypeError


@dataclass
class Movement(Entity):
    """Una entrada (cantidad positiva) o salida (negativa) de stock en una
    ubicación, con su costo por unidad base (S5.6): una entrada lo trae (la
    compra, el origen de una transferencia, la salida que se revierte), una
    salida sale al costo promedio de la ubicación"""

    product_id: int
    quantity: Decimal
    type: MovementType
    id: int | None = None
    location_id: int | None = None
    source_location_id: int | None = None
    reference_type: str | None = None
    reference_id: int | None = None
    reason: str | None = None
    date: datetime | None = None
    created_at: datetime | None = None
    unit_cost: Decimal = Decimal(0)

    @property
    def value(self) -> Decimal:
        """Cantidad con signo por costo: lo que suma o resta al valor del stock"""
        return self.quantity * self.unit_cost

    def __post_init__(self):
        if self.quantity == 0:
            raise InvalidMovementTypeError("La cantidad no puede ser cero")

        if self.type == MovementType.IN and self.quantity < 0:
            raise InvalidMovementTypeError(
                "La cantidad debe ser positiva para movimientos de entrada"
            )

        if self.type == MovementType.OUT and self.quantity > 0:
            raise InvalidMovementTypeError(
                "La cantidad debe ser negativa para movimientos de salida"
            )

        if self.unit_cost < 0:
            raise InvalidValueError("El costo unitario no puede ser negativo")
