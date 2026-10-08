from dataclasses import dataclass
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

    def mark_sold(self) -> None:
        self._transition(SerialStatus.SOLD, allowed_from=(SerialStatus.AVAILABLE,))

    def mark_reserved(self) -> None:
        self._transition(SerialStatus.RESERVED, allowed_from=(SerialStatus.AVAILABLE,))

    def mark_returned(self) -> None:
        self._transition(SerialStatus.RETURNED, allowed_from=(SerialStatus.SOLD,))

    def mark_scrapped(self) -> None:
        self.status = SerialStatus.SCRAPPED

    def change_status(self, target: SerialStatus) -> None:
        """Aplica la transición pedida; AVAILABLE no se asigna a mano"""
        transitions = {
            SerialStatus.SOLD: self.mark_sold,
            SerialStatus.RESERVED: self.mark_reserved,
            SerialStatus.RETURNED: self.mark_returned,
            SerialStatus.SCRAPPED: self.mark_scrapped,
        }
        if target not in transitions:
            raise InvalidSerialStatusError(self.serial_number, self.status, target)
        transitions[target]()

    def _transition(
        self, target: SerialStatus, allowed_from: tuple[SerialStatus, ...]
    ) -> None:
        if self.status not in allowed_from:
            raise InvalidSerialStatusError(self.serial_number, self.status, target)
        self.status = target
