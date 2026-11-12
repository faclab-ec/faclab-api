from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.shared.domain.events import DomainEvent


@dataclass
class MovementCreated(DomainEvent):
    """
    Evento emitido cuando se crea un movimiento de inventario.
    Este evento desencadena la actualización del stock correspondiente.
    """

    aggregate_id: int = 0  # movement_id
    product_id: int = 0
    quantity: Decimal = Decimal(0)
    type: str = ""  # "in" or "out"
    location_id: int | None = None
    reason: str | None = None
    date: datetime | None = None
    # Per base unit: an IN recalculates the location's average with it (S5.6)
    unit_cost: Decimal = Decimal(0)

    def _payload(self) -> dict[str, Any]:
        return {
            "movement_id": self.aggregate_id,
            "product_id": self.product_id,
            "quantity": self.quantity,
            "type": self.type,
            "location_id": self.location_id,
            "reason": self.reason,
            "unit_cost": self.unit_cost,
            "date": self.date.isoformat() if self.date else None,
        }
