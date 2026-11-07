from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.catalog.product.domain.exceptions import ConstructionMaterialTaxMismatchError
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
    barcode: str | None = None
    purchase_price: Decimal | None = None
    sale_price: Decimal | None = None
    unit_of_measure_id: int | None = None
    is_active: bool = True
    tax_code: TaxCode = TaxCode.VAT_15
    is_service: bool = False
    min_stock: int = 0
    max_stock: int | None = None
    reorder_point: int = 0
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
