"""Lo que la importación necesita leer de la empresa para validar las filas
(S5.8): pocas consultas por lote, no una por fila.

Cada método recibe las claves que aparecen en el archivo (SKUs, códigos de
barras, identificaciones) y devuelve solo las que existen. Los nombres y
códigos se comparan sin mayúsculas (`key()`); SKUs, códigos de barras e
identificaciones, tal cual.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from src.catalog.product.domain.entities import Product
from src.customers.domain.entities import Customer
from src.suppliers.domain.entities import Supplier


def key(value: str) -> str:
    """Un nombre o código como clave: sin mayúsculas ni espacios en los bordes"""
    return value.strip().casefold()


@dataclass(frozen=True)
class UnitRef:
    id: int
    symbol: str
    name: str
    decimals: int


@dataclass(frozen=True)
class PresentationRef:
    id: int
    product_id: int
    name: str
    factor: Decimal
    barcode: str | None
    sale_price: Decimal | None
    purchase_price: Decimal | None
    is_base: bool
    is_active: bool


@dataclass(frozen=True)
class PriceListRef:
    id: int
    name: str
    is_default: bool


@dataclass(frozen=True)
class PriceItemRef:
    id: int
    price_list_id: int
    presentation_id: int
    min_quantity: Decimal
    price: Decimal


@dataclass(frozen=True)
class WarehouseRef:
    id: int
    code: str


@dataclass(frozen=True)
class LocationRef:
    id: int
    warehouse_id: int
    code: str


class ImportLookups(ABC):
    @abstractmethod
    def units(self) -> dict[str, UnitRef]:
        """Por símbolo (`key`)"""

    @abstractmethod
    def categories(self) -> dict[str, int]:
        """Id por nombre (`key`); con nombres repetidos, la más antigua"""

    @abstractmethod
    def products(self, skus: Iterable[str]) -> dict[str, Product]:
        """Por SKU"""

    @abstractmethod
    def presentations(
        self, product_ids: Iterable[int]
    ) -> dict[int, list[PresentationRef]]:
        """Las de cada producto, la base incluida"""

    @abstractmethod
    def barcodes(self, barcodes: Iterable[str]) -> dict[str, PresentationRef]:
        """La presentación (de cualquier producto) que tiene cada código"""

    @abstractmethod
    def price_lists(self) -> dict[str, PriceListRef]:
        """Por nombre (`key`)"""

    @abstractmethod
    def price_items(
        self, price_list_ids: Iterable[int], product_ids: Iterable[int]
    ) -> dict[tuple[int, int, Decimal], PriceItemRef]:
        """Por (lista, presentación, cantidad mínima)"""

    @abstractmethod
    def customers(self, tax_ids: Iterable[str]) -> dict[str, Customer]:
        """Por identificación"""

    @abstractmethod
    def suppliers(self, tax_ids: Iterable[str]) -> dict[str, Supplier]:
        """Por identificación"""

    @abstractmethod
    def warehouses(self) -> dict[str, WarehouseRef]:
        """Por código (`key`)"""

    @abstractmethod
    def locations(
        self, warehouse_ids: Iterable[int]
    ) -> dict[tuple[int, str], LocationRef]:
        """Por (bodega, código `key`)"""

    @abstractmethod
    def stock(self, pairs: Iterable[tuple[int, int]]) -> dict[tuple[int, int], Decimal]:
        """La cantidad de cada (producto, ubicación) que tiene fila de stock"""
