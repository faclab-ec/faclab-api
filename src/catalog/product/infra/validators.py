from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from src.shared.domain.tax import TaxCode
from src.shared.infra.validators import DecimalNumber, QueryParams


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

    barcode: str | None = Field(None, description="Barcode (EAN/UPC)")
    category_id: int | None = Field(None, ge=1, description="Category ID")
    unit_of_measure_id: int | None = Field(None, ge=1, description="Unit of measure ID")
    purchase_price: DecimalNumber | None = Field(
        None, ge=0, description="Purchase price per unit"
    )
    sale_price: DecimalNumber | None = Field(
        None, ge=0, description="Sale price per unit"
    )
    tax_code: TaxCode = Field(
        TaxCode.VAT_15, description="Semantic VAT code (see TaxCode enum)"
    )
    is_active: bool = Field(True, description="Whether the product is active")
    is_service: bool = Field(
        False, description="True if this is a service (no inventory tracking)"
    )
    min_stock: int = Field(
        0, ge=0, description="Minimum stock level — triggers low-stock alert"
    )
    max_stock: int | None = Field(
        None, ge=0, description="Maximum recommended stock level"
    )
    reorder_point: int = Field(0, ge=0, description="Stock level at which to reorder")
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


class ProductResponse(ProductRequest):
    id: int = Field(ge=1, description="Product ID")


# Query Params
class CategoryQueryParams(QueryParams):
    pass


class ProductQueryParams(QueryParams):
    category_id: int | None = Field(None, ge=1, description="Filter by category ID")
    search: str | None = Field(
        None,
        min_length=1,
        max_length=100,
        description="Text to look for in the name or SKU, or an exact barcode (case-insensitive)",
    )
