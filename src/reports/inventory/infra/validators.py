from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.shared.infra.validators import DecimalNumber, QueryParams

# ---------------------------------------------------------------------------
# Valuation
# ---------------------------------------------------------------------------


class ValuationItemResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    product_id: int = Field(description="Product ID")
    product_name: str = Field(description="Product name")
    sku: str = Field(description="Product SKU")
    quantity: int = Field(description="Current stock quantity")
    average_cost: DecimalNumber = Field(description="Weighted average cost per unit")
    total_value: DecimalNumber = Field(
        description="Total inventory value (quantity x average cost)"
    )


class InventoryValuationResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    total_value: DecimalNumber = Field(description="Grand total inventory value")
    as_of_date: date = Field(description="Valuation date")
    items: list[ValuationItemResponse] = Field(
        description="Per-product valuation breakdown"
    )


class ValuationQueryParams(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    warehouse_id: int | None = Field(None, ge=1, description="Filter by warehouse ID")
    as_of_date: date | None = Field(
        None, description="Valuation date (defaults to today)"
    )


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------


class ProductRotationResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    product_id: int = Field(description="Product ID")
    product_name: str = Field(description="Product name")
    sku: str = Field(description="Product SKU")
    total_in: int = Field(description="Total units received in the period")
    total_out: int = Field(description="Total units sold/consumed in the period")
    current_stock: int = Field(description="Current stock quantity")
    turnover_rate: DecimalNumber = Field(
        description="Inventory turnover rate for the period"
    )
    days_of_stock: int | None = Field(
        None, description="Estimated days of stock remaining"
    )


class RotationQueryParams(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    # Defaults live in GetProductRotationQuery: FastAPI ignores default_factory
    # on query models, so an omitted date would fail validation.
    from_date: date | None = Field(
        None, description="Start date (defaults to first day of current month)"
    )
    to_date: date | None = Field(None, description="End date (defaults to today)")
    warehouse_id: int | None = Field(None, ge=1, description="Filter by warehouse ID")


# ---------------------------------------------------------------------------
# Movement History
# ---------------------------------------------------------------------------


class MovementHistoryItemResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int = Field(description="Movement ID")
    product_id: int = Field(description="Product ID")
    product_name: str = Field(description="Product name")
    sku: str = Field(description="Product SKU")
    quantity: int = Field(
        description="Movement quantity (positive = IN, negative = OUT)"
    )
    type: str = Field(description="Movement type (IN or OUT)")
    location_id: int | None = Field(None, description="Storage location ID")
    source_location_id: int | None = Field(
        None, description="Source location for transfers"
    )
    reference_type: str | None = Field(
        None, description="Source entity type (e.g. sale, purchase_order)"
    )
    reference_id: int | None = Field(None, description="Source entity ID")
    reason: str | None = Field(None, description="Reason for the movement")
    date: datetime | None = Field(None, description="Movement date")
    created_at: datetime | None = Field(None, description="Record creation timestamp")


class MovementHistoryQueryParams(QueryParams):
    limit: int | None = Field(
        50, ge=1, le=500, description="Maximum records to return (1-500)"
    )
    product_id: int | None = Field(None, ge=1, description="Filter by product ID")
    type: str | None = Field(None, description="Filter by movement type (IN or OUT)")
    from_date: date | None = Field(None, description="Start date (inclusive)")
    to_date: date | None = Field(None, description="End date (inclusive)")
    warehouse_id: int | None = Field(None, ge=1, description="Filter by warehouse ID")


# ---------------------------------------------------------------------------
# Warehouse Summary
# ---------------------------------------------------------------------------


class WarehouseSummaryResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    warehouse_id: int = Field(description="Warehouse ID")
    warehouse_name: str = Field(description="Warehouse name")
    warehouse_code: str = Field(description="Warehouse code")
    total_products: int = Field(description="Number of distinct products stored")
    total_quantity: int = Field(description="Total stock quantity across all products")
    reserved_quantity: int = Field(description="Total reserved quantity")
    available_quantity: int = Field(description="Available quantity (total - reserved)")
    total_value: DecimalNumber = Field(description="Total inventory value")


class SummaryQueryParams(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    warehouse_id: int | None = Field(
        None, ge=1, description="Filter by warehouse ID (omit for all warehouses)"
    )
