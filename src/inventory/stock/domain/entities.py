from dataclasses import dataclass
from decimal import Decimal

from src.inventory.stock.domain.exceptions import InsufficientStockError
from src.shared.domain.entities import Entity
from src.shared.domain.money import round_cost


def weighted_average(
    quantity: Decimal, average_cost: Decimal, received: Decimal, unit_cost: Decimal
) -> Decimal:
    """Costo promedio ponderado tras una entrada: lo que había a su promedio y
    lo que entra a su costo, sobre la cantidad nueva, a 6 decimales. Sin
    existencias (la cantidad nunca es negativa, S3.2) queda el costo de la
    entrada."""
    total = quantity + received
    if quantity <= 0 or total <= 0:
        return round_cost(unit_cost)
    return round_cost((quantity * average_cost + received * unit_cost) / total)


@dataclass
class Stock(Entity):
    """Lo que hay de un producto en una ubicación y su costo promedio
    ponderado (S5.6): cada entrada lo recalcula con su costo, cada salida sale
    a él sin cambiarlo. Vive en la fila que bloquea toda entrada y salida."""

    product_id: int
    quantity: Decimal
    id: int | None = None
    location_id: int | None = None
    reserved_quantity: Decimal = Decimal(0)
    average_cost: Decimal = Decimal(0)

    @property
    def available_quantity(self) -> Decimal:
        return self.quantity - self.reserved_quantity

    @property
    def value(self) -> Decimal:
        return self.quantity * self.average_cost

    def update_quantity(self, delta: Decimal, unit_cost: Decimal | None = None) -> None:
        """Suma `delta` (negativo para salidas). Una salida solo toma lo
        disponible: nunca deja la cantidad bajo cero ni bajo lo reservado. Una
        entrada con `unit_cost` recalcula el promedio ponderado; sin él entra
        al promedio vigente"""
        if delta < 0 and -delta > self.available_quantity:
            raise InsufficientStockError(self.product_id, delta)
        if delta > 0 and unit_cost is not None:
            self.average_cost = weighted_average(
                self.quantity, self.average_cost, delta, unit_cost
            )
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
