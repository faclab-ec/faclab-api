from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from src.pricing.domain.exceptions import (
    DefaultPriceListBasePriceError,
    DefaultPriceListLockedError,
    InvalidPriceListItemError,
    InvalidPriceListValidityError,
)
from src.shared.domain.entities import Entity


@dataclass
class PriceList(Entity):
    """Una lista de precios de la empresa (S5.3): minorista, mayorista, por
    volumen.

    Se asigna a un cliente o a una sucursal; una venta toma la del cliente, luego
    la de su sucursal y al final la general. La general (`is_default`, una por
    empresa) no guarda el precio base: ese es el del producto y sus
    presentaciones; solo tiene escalas por volumen para todos. Una lista inactiva
    o fuera de su vigencia (fechas inclusivas) no aplica.
    """

    name: str
    id: int | None = None
    description: str | None = None
    is_default: bool = False
    is_active: bool = True
    valid_from: date | None = None
    valid_to: date | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        self._ensure_valid(self.is_active, self.valid_from, self.valid_to)

    def _ensure_valid(
        self, is_active: bool, valid_from: date | None, valid_to: date | None
    ) -> None:
        if valid_from and valid_to and valid_from > valid_to:
            raise InvalidPriceListValidityError()
        if self.is_default and (not is_active or valid_from or valid_to):
            raise DefaultPriceListLockedError()

    def applies_on(self, day: date) -> bool:
        """Si la lista rige ese día"""
        if not self.is_active:
            return False
        if self.valid_from is not None and day < self.valid_from:
            return False
        return self.valid_to is None or day <= self.valid_to

    def change(
        self,
        *,
        name: str,
        description: str | None,
        is_active: bool,
        valid_from: date | None,
        valid_to: date | None,
    ) -> None:
        self._ensure_valid(is_active, valid_from, valid_to)
        self.name = name
        self.description = description
        self.is_active = is_active
        self.valid_from = valid_from
        self.valid_to = valid_to

    def ensure_deletable(self) -> None:
        if self.is_default:
            raise DefaultPriceListLockedError("The general price list can't be deleted")

    def ensure_accepts(self, min_quantity: Decimal) -> None:
        """La general solo guarda escalas: su precio base es el del producto"""
        if self.is_default and min_quantity <= 0:
            raise DefaultPriceListBasePriceError()


@dataclass
class PriceListItem(Entity):
    """El precio de una presentación de un producto en una lista, desde una
    cantidad (en esa presentación). `min_quantity` 0 es el precio base de la
    lista; uno mayor es una escala por volumen ("desde 10 sacos")."""

    price_list_id: int
    product_id: int
    presentation_id: int
    price: Decimal
    min_quantity: Decimal = Decimal(0)
    id: int | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        self._ensure_valid(self.price, self.min_quantity)

    @staticmethod
    def _ensure_valid(price: Decimal, min_quantity: Decimal) -> None:
        if Decimal(str(price)) < 0:
            raise InvalidPriceListItemError("A price can't be negative")
        if Decimal(str(min_quantity)) < 0:
            raise InvalidPriceListItemError("A minimum quantity can't be negative")

    def change(self, *, price: Decimal, min_quantity: Decimal) -> None:
        self._ensure_valid(price, min_quantity)
        self.price = price
        self.min_quantity = min_quantity
