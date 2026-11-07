from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.shared.domain.entities import Entity

from .constants import MovementType
from .exceptions import InvalidMovementTypeError


@dataclass
class Movement(Entity):
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
