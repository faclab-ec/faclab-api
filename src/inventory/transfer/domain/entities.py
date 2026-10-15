from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from src.inventory.transfer.domain.exceptions import (
    InvalidTransferStatusError,
    SameLocationTransferError,
)
from src.shared.domain.entities import Entity
from src.shared.domain.exceptions import ValidationError


class TransferStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    RECEIVED = "received"
    CANCELLED = "cancelled"


@dataclass
class StockTransfer(Entity):
    source_location_id: int
    destination_location_id: int
    status: TransferStatus = TransferStatus.DRAFT
    id: int | None = None
    transfer_date: datetime | None = None
    requested_by: str | None = None
    notes: str | None = None
    created_at: datetime | None = None

    def __post_init__(self):
        if self.source_location_id == self.destination_location_id:
            raise SameLocationTransferError()

    def ensure_draft(self, operation: str) -> None:
        if self.status != TransferStatus.DRAFT:
            raise InvalidTransferStatusError(self.status, operation)

    def update_details(self, notes: str | None = None) -> None:
        """Actualiza los datos editables; solo en DRAFT. El solicitante no
        cambia: es el usuario que creó la transferencia"""
        self.ensure_draft("actualizar")
        if notes is not None:
            self.notes = notes

    def confirm(self) -> None:
        self.ensure_draft("confirmar")
        self.status = TransferStatus.CONFIRMED

    def receive(self) -> None:
        if self.status != TransferStatus.CONFIRMED:
            raise InvalidTransferStatusError(self.status, "recibir")
        self.status = TransferStatus.RECEIVED

    def cancel(self) -> None:
        if self.status == TransferStatus.RECEIVED:
            raise InvalidTransferStatusError(self.status, "cancelar")
        self.status = TransferStatus.CANCELLED


@dataclass
class StockTransferItem(Entity):
    transfer_id: int
    product_id: int
    quantity: int
    id: int | None = None
    lot_id: int | None = None
    notes: str | None = None

    def __post_init__(self):
        _ensure_positive(self.quantity)

    def update(self, quantity: int | None = None, notes: str | None = None) -> None:
        if quantity is not None:
            _ensure_positive(quantity)
            self.quantity = quantity
        if notes is not None:
            self.notes = notes


def _ensure_positive(quantity: int) -> None:
    if quantity <= 0:
        raise ValidationError("La cantidad debe ser mayor a cero")
