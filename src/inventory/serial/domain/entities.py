from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from src.inventory.serial.domain.exceptions import InvalidSerialStatusError
from src.shared.domain.entities import Entity


class SerialStatus(StrEnum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    SOLD = "sold"
    RETURNED = "returned"
    SCRAPPED = "scrapped"


@dataclass
class SerialNumber(Entity):
    product_id: int
    serial_number: str
    status: SerialStatus = SerialStatus.AVAILABLE
    id: int | None = None
    lot_id: int | None = None
    location_id: int | None = None
    purchase_order_id: int | None = None
    sale_id: int | None = None
    created_at: datetime | None = None
    notes: str | None = None

    def mark_sold(self) -> "SerialNumber":
        if self.status != SerialStatus.AVAILABLE:
            raise InvalidSerialStatusError(
                self.serial_number, self.status, SerialStatus.SOLD
            )
        return replace(self, status=SerialStatus.SOLD)

    def mark_reserved(self) -> "SerialNumber":
        if self.status != SerialStatus.AVAILABLE:
            raise InvalidSerialStatusError(
                self.serial_number, self.status, SerialStatus.RESERVED
            )
        return replace(self, status=SerialStatus.RESERVED)

    def mark_returned(self) -> "SerialNumber":
        if self.status != SerialStatus.SOLD:
            raise InvalidSerialStatusError(
                self.serial_number, self.status, SerialStatus.RETURNED
            )
        return replace(self, status=SerialStatus.RETURNED)

    def mark_scrapped(self) -> "SerialNumber":
        return replace(self, status=SerialStatus.SCRAPPED)
