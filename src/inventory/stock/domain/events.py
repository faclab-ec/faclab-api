from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.shared.domain.events import DomainEvent


@dataclass
class StockCreated(DomainEvent):
    aggregate_id: int = 0  # stock_id
    product_id: int = 0
    quantity: Decimal = Decimal(0)
    location_id: int | None = None

    def _payload(self) -> dict[str, Any]:
        return {
            "stock_id": self.aggregate_id,
            "product_id": self.product_id,
            "quantity": self.quantity,
            "location_id": self.location_id,
        }


@dataclass
class StockUpdated(DomainEvent):
    aggregate_id: int = 0  # stock_id
    product_id: int = 0
    old_quantity: Decimal = Decimal(0)
    new_quantity: Decimal = Decimal(0)
    location_id: int | None = None

    def _payload(self) -> dict[str, Any]:
        return {
            "stock_id": self.aggregate_id,
            "product_id": self.product_id,
            "old_quantity": self.old_quantity,
            "new_quantity": self.new_quantity,
            "location_id": self.location_id,
        }
