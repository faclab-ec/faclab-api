from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from src.shared.domain.tax import ConstructionMaterialCode, TaxCode
from src.shared.infra.validators import DecimalNumber, QuantityNumber, QueryParams


# Requests
class CategoryRequest(BaseModel):
    name: str = Field(description="Category name")
    description: str | None = Field(None, description="Optional description")


class ProductRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    name: str = Field(description="Product name")
    sku: str = Field(description="Stock Keeping Unit — unique product code")
    description: str | None = Field(None, description="Product description")

    @field_validator("barcode", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: str | None) -> str | None:
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    barcode: str | None = Field(
        None,
        description="Barcode (EAN/UPC) of the base unit, kept in the product's "
        "base presentation. Unique in the company among every presentation",
    )
    category_id: int | None = Field(None, ge=1, description="Category ID")
    unit_of_measure_id: int = Field(
        ge=1,
        description="Base unit of measure, the one stock is kept in. Its name is "
        "the name of the product's base presentation",
    )
    purchase_price: DecimalNumber | None = Field(
        None, ge=0, description="Purchase price per base unit"
    )
    sale_price: DecimalNumber | None = Field(
        None, ge=0, description="Sale price per base unit"
    )
    tax_code: TaxCode = Field(
        TaxCode.VAT_15, description="Semantic VAT code (see TaxCode enum)"
    )
    construction_material_code: ConstructionMaterialCode | None = Field(
        None,
        description=(
            "SRI subcategory of a construction material (Table 31 of the technical "
            "sheet), written in the invoice's codigoAuxiliar. Requires taxCode VAT_5"
        ),
    )
    is_active: bool = Field(True, description="Whether the product is active")
    is_service: bool = Field(
        False, description="True if this is a service (no inventory tracking)"
    )
    min_stock: QuantityNumber = Field(
        Decimal(0),
        ge=0,
        description="Minimum stock level — triggers low-stock alert. Takes the "
        "decimals of the product's unit of measure",
    )
    max_stock: QuantityNumber | None = Field(
        None, ge=0, description="Maximum recommended stock level"
    )
    reorder_point: QuantityNumber = Field(
        Decimal(0), ge=0, description="Stock level at which to reorder"
    )
    lead_time_days: int | None = Field(
        None, ge=0, description="Supplier lead time in days"
    )

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "name": "Laptop Dell Inspiron 15",
                    "sku": "DELL-INS-15",
                    "description": "Dell Inspiron 15 laptop, 16GB RAM, 512GB SSD",
                    "barcode": "7501234567890",
                    "categoryId": 1,
                    "unitOfMeasureId": 1,
                    "purchasePrice": 650.00,
                    "salePrice": 899.99,
                    "taxCode": "VAT_15",
                    "isActive": True,
                    "isService": False,
                    "minStock": 5,
                    "maxStock": 50,
                    "reorderPoint": 10,
                    "leadTimeDays": 7,
                }
            ]
        },
    )


# Responses
class CategoryResponse(CategoryRequest):
    id: int = Field(ge=1, description="Category ID")


class ProductPresentationRequest(BaseModel):
    """A presentation of a product (S5.2): box of 100, roll of 50 m"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    @field_validator("barcode", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: str | None) -> str | None:
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    name: str = Field(min_length=1, max_length=64, description="Box x100, Roll 50 m")
    factor: QuantityNumber = Field(
        gt=0,
        description="Base units in one presentation, greater than zero. Takes the "
        "decimals of the product's unit of measure. 1 in the base presentation",
    )
    barcode: str | None = Field(
        None, max_length=64, description="Barcode, unique in the company"
    )
    sale_price: DecimalNumber | None = Field(
        None,
        ge=0,
        description="Sale price of one presentation. Null: factor × the product's "
        "sale price. Always null in the base presentation",
    )
    purchase_price: DecimalNumber | None = Field(
        None,
        ge=0,
        description="Cost of one presentation. Null: factor × the product's purchase "
        "price. Always null in the base presentation",
    )
    is_active: bool = Field(
        True, description="An inactive presentation can't be sold or bought"
    )


class ProductPresentationResponse(ProductPresentationRequest):
    id: int = Field(ge=1, description="Presentation ID")
    product_id: int = Field(ge=1, description="Product ID")
    is_base: bool = Field(
        description="The product's unit of measure: factor 1, named after the unit, "
        "with the product's barcode and prices. Only its barcode changes"
    )
    effective_sale_price: DecimalNumber | None = Field(
        description="Price a sale takes by default: its own or factor × the "
        "product's (null when neither exists)"
    )
    effective_purchase_price: DecimalNumber | None = Field(
        description="Cost a purchase order takes by default: its own or factor × "
        "the product's"
    )
    quantity_decimals: int = Field(
        description="Decimals a quantity in this presentation takes: those of the "
        "unit minus those of the factor, so its base units fit the unit"
    )


class ProductResponse(ProductRequest):
    id: int = Field(ge=1, description="Product ID")
    unit_symbol: str | None = Field(
        description="Symbol of the product's unit of measure"
    )
    quantity_decimals: int = Field(
        description="Decimals a quantity of this product takes in its base unit: "
        "those of its unit of measure"
    )
    presentations: list[ProductPresentationResponse] = Field(
        default_factory=list,
        description="Its presentations: the base one first, then by factor",
    )


class ProductBarcodeResponse(BaseModel):
    """What a scanned barcode is: the product and the presentation it sells"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    product: ProductResponse
    presentation: ProductPresentationResponse


# Query Params
class CategoryQueryParams(QueryParams):
    pass


class ProductQueryParams(QueryParams):
    category_id: int | None = Field(None, ge=1, description="Filter by category ID")
    search: str | None = Field(
        None,
        min_length=1,
        max_length=100,
        description="Text to look for in the name or SKU (case-insensitive), or the "
        "exact barcode of an active presentation",
    )
