from pydantic import Field

from src.public_api.infra.schemas.base import Id, PublicInput, PublicModel, SyncParams
from src.public_api.infra.types import Money, MoneyInput, Quantity, Timestamp
from src.shared.domain.tax import ConstructionMaterialCode, TaxCode


class ProductPresentation(PublicModel):
    """A way the product is sold: the base unit, a box of 100, a roll of 50 m"""

    id: int
    name: str
    factor: Quantity = Field(description="Base units in one of it")
    barcode: str | None = None
    is_base: bool
    is_active: bool
    sale_price: Money | None = Field(
        None, description="Its own sale price, or the product's times its factor"
    )
    quantity_decimals: int = Field(description="Decimals a quantity in it takes")


class Product(PublicModel):
    id: int
    sku: str
    name: str
    description: str | None = None
    category_id: int | None = None
    unit_of_measure_id: int
    unit_symbol: str | None = None
    quantity_decimals: int = Field(description="Decimals a base quantity takes")
    tax_code: TaxCode
    construction_material_code: ConstructionMaterialCode | None = None
    sale_price: Money | None = None
    is_active: bool
    is_service: bool
    barcode: str | None = Field(None, description="The base presentation's")
    presentations: list[ProductPresentation]
    created_at: Timestamp
    updated_at: Timestamp


class ProductInput(PublicInput):
    """Every editable field: a PUT replaces them all"""

    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(None, max_length=255)
    category_id: Id | None = None
    unit_of_measure_id: Id
    sale_price: MoneyInput | None = None
    tax_code: TaxCode = TaxCode.VAT_15
    construction_material_code: ConstructionMaterialCode | None = None
    barcode: str | None = Field(
        None, max_length=64, description="The base presentation's"
    )
    is_active: bool = True
    is_service: bool = False


class ProductListParams(SyncParams):
    sku: str | None = None
    barcode: str | None = Field(None, description="Of any of its presentations")
    search: str | None = Field(
        None, description="In the name or SKU, or an active presentation's barcode"
    )
