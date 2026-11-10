from dataclasses import dataclass
from decimal import Decimal

from src.inventory.stock.domain.exceptions import InsufficientStockError
from src.shared.domain.entities import Entity


@dataclass
class Stock(Entity):
    product_id: int
    quantity: Decimal
    id: int | None = None
    location_id: int | None = None
    reserved_quantity: Decimal = Decimal(0)

    @property
    def available_quantity(self) -> Decimal:
        return self.quantity - self.reserved_quantity

    def update_quantity(self, delta: Decimal) -> None:
        """Suma `delta` (negativo para salidas). Una salida solo toma lo
        disponible: nunca deja la cantidad bajo cero ni bajo lo reservado"""
        if delta < 0 and -delta > self.available_quantity:
            raise InsufficientStockError(self.product_id, delta)
        self.quantity += delta

    def reserve(self, quantity: Decimal) -> None:
        """Aparta unidades disponibles (p. ej. al confirmar una transferencia)"""
        if quantity > self.available_quantity:
            raise InsufficientStockError(self.product_id, quantity)
        self.reserved_quantity += quantity

    def release(self, quantity: Decimal) -> None:
        """Libera una reserva. Nunca deja la reserva negativa, aunque los datos
        previos estén desfasados, para no bloquear la recepción o cancelación."""
        self.reserved_quantity = max(self.reserved_quantity - quantity, Decimal(0))
