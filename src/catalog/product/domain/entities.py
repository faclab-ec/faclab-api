from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.catalog.product.domain.exceptions import (
    BasePresentationFixedError,
    ConstructionMaterialTaxMismatchError,
    InvalidPresentationFactorError,
)
from src.shared.domain.entities import Entity
from src.shared.domain.tax import (
    CONSTRUCTION_MATERIAL_TAX_CODE,
    ConstructionMaterialCode,
    TaxCode,
)


@dataclass
class Category(Entity):
    name: str
    description: str | None
    id: int | None = None


@dataclass
class Product(Entity):
    name: str
    sku: str
    id: int | None = None
    description: str | None = None
    category_id: int | None = None
    purchase_price: Decimal | None = None
    sale_price: Decimal | None = None
    # Unidad base, en la que se lleva el stock: obligatoria desde S5.2 (None
    # solo en entidades de prueba)
    unit_of_measure_id: int | None = None
    is_active: bool = True
    tax_code: TaxCode = TaxCode.VAT_15
    is_service: bool = False
    min_stock: Decimal = Decimal(0)
    max_stock: Decimal | None = None
    reorder_point: Decimal = Decimal(0)
    lead_time_days: int | None = None
    construction_material_code: ConstructionMaterialCode | None = None
    created_at: datetime | None = None

    def ensure_material_tax(self) -> None:
        """A material of the SRI's list carries its rate. Not on every load: a row
        written under a former rate must stay readable when the law changes."""
        if (
            self.construction_material_code is not None
            and self.tax_code != CONSTRUCTION_MATERIAL_TAX_CODE
        ):
            raise ConstructionMaterialTaxMismatchError()


# Escala de los precios de una presentación, la de MoneyColumn
PRICE_SCALE = Decimal("0.000001")


@dataclass
class ProductPresentation(Entity):
    """Una forma de vender o comprar un producto (S5.2): caja de 100, rollo de 50 m.

    `factor` es cuántas unidades base contiene, mayor que cero. Cada producto tiene
    una presentación base (factor 1), su unidad de medida: lleva su nombre, el
    código de barras del producto y sus precios son los del producto. Las demás
    tienen precio y costo propios o, sin ellos, factor × los del producto. El
    código de barras es único en la empresa.
    """

    product_id: int
    name: str
    factor: Decimal = Decimal(1)
    id: int | None = None
    barcode: str | None = None
    sale_price: Decimal | None = None
    purchase_price: Decimal | None = None
    is_base: bool = False
    is_active: bool = True
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.factor <= 0:
            raise InvalidPresentationFactorError()
        if self.is_base and (
            self.factor != 1
            or self.sale_price is not None
            or self.purchase_price is not None
            or not self.is_active
        ):
            raise BasePresentationFixedError(
                "A base presentation has factor 1, the product's prices and stays active"
            )

    def base_quantity(self, quantity: Decimal) -> Decimal:
        """Una cantidad en esta presentación, en unidades base"""
        return quantity * self.factor

    def effective_sale_price(
        self, product_price: Decimal | float | None
    ) -> Decimal | None:
        """Precio de venta de una unidad de esta presentación"""
        return _effective(self.sale_price, product_price, self.factor)

    def effective_purchase_price(
        self, product_cost: Decimal | float | None
    ) -> Decimal | None:
        """Costo de una unidad de esta presentación"""
        return _effective(self.purchase_price, product_cost, self.factor)

    def change(
        self,
        *,
        name: str,
        factor: Decimal,
        barcode: str | None,
        sale_price: Decimal | None,
        purchase_price: Decimal | None,
        is_active: bool,
    ) -> None:
        """Reemplaza sus datos; de la base solo cambia el código de barras"""
        if self.is_base:
            if (name, factor, sale_price, purchase_price, is_active) != (
                self.name,
                Decimal(1),
                None,
                None,
                True,
            ):
                raise BasePresentationFixedError()
            self.barcode = barcode
            return
        if factor <= 0:
            raise InvalidPresentationFactorError()
        self.name = name
        self.factor = factor
        self.barcode = barcode
        self.sale_price = sale_price
        self.purchase_price = purchase_price
        self.is_active = is_active


def _effective(
    own: Decimal | float | None,
    product_value: Decimal | float | None,
    factor: Decimal,
) -> Decimal | None:
    # A product built from a request may carry its prices as floats
    if own is not None:
        return Decimal(str(own))
    if product_value is None:
        return None
    return (Decimal(str(product_value)) * factor).quantize(PRICE_SCALE)
