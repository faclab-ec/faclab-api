from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from src.inventory.transfer.domain.exceptions import InvalidTransferStatusError
from src.shared.domain.entities import Entity


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

    def confirm(self) -> "StockTransfer":
        if self.status != TransferStatus.DRAFT:
            raise InvalidTransferStatusError(self.status, "confirmar")
        return replace(self, status=TransferStatus.CONFIRMED)

    def receive(self) -> "StockTransfer":
        if self.status != TransferStatus.CONFIRMED:
            raise InvalidTransferStatusError(self.status, "recibir")
        return replace(self, status=TransferStatus.RECEIVED)

    def cancel(self) -> "StockTransfer":
        if self.status == TransferStatus.RECEIVED:
            raise InvalidTransferStatusError(self.status, "cancelar")
        return replace(self, status=TransferStatus.CANCELLED)


@dataclass
class StockTransferItem(Entity):
    transfer_id: int
    product_id: int
    quantity: int
    id: int | None = None
    lot_id: int | None = None
    notes: str | None = None
