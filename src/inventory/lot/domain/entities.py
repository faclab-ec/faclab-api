from dataclasses import dataclass
from datetime import date, datetime

from src.shared.domain.entities import Entity
from src.shared.domain.exceptions import ValidationError


@dataclass
class Lot(Entity):
    product_id: int
    lot_number: str
    id: int | None = None
    manufacture_date: date | None = None
    expiration_date: date | None = None
    initial_quantity: int = 0
    current_quantity: int = 0
    notes: str | None = None
    created_at: datetime | None = None

    @property
    def is_expired(self) -> bool:
        if self.expiration_date is None:
            return False
        return date.today() > self.expiration_date

    @property
    def days_to_expiry(self) -> int | None:
        if self.expiration_date is None:
            return None
        return (self.expiration_date - date.today()).days

    def receive(self, quantity: int) -> None:
        """Suma unidades recibidas (p. ej. otra recepción del mismo lote)"""
        self.initial_quantity += quantity
        self.current_quantity += quantity

    def update_details(
        self,
        current_quantity: int | None = None,
        manufacture_date: date | None = None,
        expiration_date: date | None = None,
        notes: str | None = None,
    ) -> None:
        if current_quantity is not None:
            if current_quantity < 0:
                raise ValidationError(
                    f"Current quantity cannot be negative. Received: {current_quantity}"
                )
            self.current_quantity = current_quantity
        if manufacture_date is not None:
            self.manufacture_date = manufacture_date
        if expiration_date is not None:
            self.expiration_date = expiration_date
        if notes is not None:
            self.notes = notes

    def dict(self):
        return {
            **super().dict(),
            "is_expired": self.is_expired,
            "days_to_expiry": self.days_to_expiry,
        }


@dataclass
class MovementLotItem(Entity):
    movement_id: int
    lot_id: int
    quantity: int
    id: int | None = None
