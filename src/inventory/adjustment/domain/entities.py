from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from src.inventory.adjustment.domain.exceptions import InvalidAdjustmentStatusError
from src.shared.domain.entities import Entity


class AdjustmentStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class AdjustmentReason(StrEnum):
    PHYSICAL_COUNT = "physical_count"
    DAMAGED = "damaged"
    THEFT = "theft"
    EXPIRATION = "expiration"
    SUPPLIER_ERROR = "supplier_error"
    CORRECTION = "correction"
    OTHER = "other"


@dataclass
class InventoryAdjustment(Entity):
    warehouse_id: int
    reason: AdjustmentReason
    status: AdjustmentStatus = AdjustmentStatus.DRAFT
    id: int | None = None
    adjustment_date: datetime | None = None
    notes: str | None = None
    adjusted_by: str | None = None
    created_at: datetime | None = None

    def confirm(self) -> "InventoryAdjustment":
        if self.status != AdjustmentStatus.DRAFT:
            raise InvalidAdjustmentStatusError(self.status, "confirmar")
        return replace(self, status=AdjustmentStatus.CONFIRMED)

    def cancel(self) -> "InventoryAdjustment":
        if self.status == AdjustmentStatus.CONFIRMED:
            raise InvalidAdjustmentStatusError(self.status, "cancelar")
        return replace(self, status=AdjustmentStatus.CANCELLED)


@dataclass
class AdjustmentItem(Entity):
    adjustment_id: int
    product_id: int
    location_id: int
    expected_quantity: int
    actual_quantity: int
    id: int | None = None
    lot_id: int | None = None
    notes: str | None = None

    @property
    def difference(self) -> int:
        return self.actual_quantity - self.expected_quantity
