from dataclasses import dataclass
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

    def ensure_draft(self, operation: str) -> None:
        if self.status != AdjustmentStatus.DRAFT:
            raise InvalidAdjustmentStatusError(self.status, operation)

    def update_details(
        self, notes: str | None = None, adjusted_by: str | None = None
    ) -> None:
        """Actualiza los datos editables; solo en DRAFT"""
        self.ensure_draft("actualizar")
        if notes is not None:
            self.notes = notes
        if adjusted_by is not None:
            self.adjusted_by = adjusted_by

    def confirm(self) -> None:
        self.ensure_draft("confirmar")
        self.status = AdjustmentStatus.CONFIRMED

    def cancel(self) -> None:
        if self.status == AdjustmentStatus.CONFIRMED:
            raise InvalidAdjustmentStatusError(self.status, "cancelar")
        self.status = AdjustmentStatus.CANCELLED


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

    def update(
        self, actual_quantity: int | None = None, notes: str | None = None
    ) -> None:
        if actual_quantity is not None:
            self.actual_quantity = actual_quantity
        if notes is not None:
            self.notes = notes
