from dataclasses import dataclass

from src.inventory.stock.domain.exceptions import InsufficientStockError
from src.shared.domain.entities import Entity


@dataclass
class Stock(Entity):
    product_id: int
    quantity: int
    id: int | None = None
    location_id: int | None = None
    reserved_quantity: int = 0

    @property
    def available_quantity(self) -> int:
        return self.quantity - self.reserved_quantity

    def update_quantity(self, delta: int) -> None:
        """Suma `delta` (negativo para salidas) sin dejar la cantidad bajo cero"""
        new_quantity = self.quantity + delta
        if new_quantity < 0:
            raise InsufficientStockError(self.product_id, delta)
        self.quantity = new_quantity

    def reserve(self, quantity: int) -> None:
        """Aparta unidades disponibles (p. ej. al confirmar una transferencia)"""
        if quantity > self.available_quantity:
            raise InsufficientStockError(self.product_id, quantity)
        self.reserved_quantity += quantity

    def release(self, quantity: int) -> None:
        """Libera una reserva. Nunca deja la reserva negativa, aunque los datos
        previos estén desfasados, para no bloquear la recepción o cancelación."""
        self.reserved_quantity = max(self.reserved_quantity - quantity, 0)
