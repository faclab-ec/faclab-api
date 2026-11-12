from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.shared.infra.validators import DecimalNumber, QuantityNumber, QueryParams

# ---------------------------------------------------------------------------
# Valuation
# ---------------------------------------------------------------------------


class ValuationItemResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    product_id: int = Field(description="Product ID")
    product_name: str = Field(description="Product name")
    sku: str = Field(description="Product SKU")
    quantity: QuantityNumber = Field(description="Stock quantity, in base units")
    average_cost: DecimalNumber = Field(
        description="Weighted average cost per base unit: total value / quantity"
    )
    total_value: DecimalNumber = Field(
        description="Inventory value: each location's quantity x its average cost "
        "(at a date, each movement's quantity x the cost it moved at)"
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
    total_in: QuantityNumber = Field(description="Total units received in the period")
    total_out: QuantityNumber = Field(
        description="Total units sold/consumed in the period"
    )
    current_stock: QuantityNumber = Field(description="Current stock quantity")
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
    quantity: QuantityNumber = Field(
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
    unit_cost: DecimalNumber = Field(
        description="Cost per base unit it moved at (an OUT: its location's average)"
    )


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
    total_quantity: QuantityNumber = Field(
        description="Total stock quantity across all products"
    )
    reserved_quantity: QuantityNumber = Field(description="Total reserved quantity")
    available_quantity: QuantityNumber = Field(
        description="Available quantity (total - reserved)"
    )
    total_value: DecimalNumber = Field(description="Total inventory value")


class SummaryQueryParams(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    warehouse_id: int | None = Field(
        None, ge=1, description="Filter by warehouse ID (omit for all warehouses)"
    )


# ---------------------------------------------------------------------------
# Kardex
# ---------------------------------------------------------------------------


class KardexBalanceResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    quantity: QuantityNumber = Field(description="Quantity, in base units")
    value: DecimalNumber = Field(description="Value at the cost each movement had")
    average_cost: DecimalNumber | None = Field(
        None, description="value / quantity; null without stock"
    )


class KardexTotalResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    quantity: QuantityNumber = Field(description="Quantity, in base units")
    value: DecimalNumber = Field(description="Value")


class KardexEntryResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    movement_id: int = Field(description="Movement ID")
    date: datetime | None = Field(None, description="Movement date")
    type: str = Field(description="IN or OUT")
    location_id: int | None = Field(None, description="Location it moved in")
    location_name: str | None = Field(None, description="Location name")
    reference_type: str | None = Field(
        None,
        description="Document that moved it (sale, refund, purchase_order, "
        "supplier_return, adjustment, transfer); none for a manual movement",
    )
    reference_id: int | None = Field(None, description="Document ID")
    reason: str | None = Field(None, description="Reason")
    in_quantity: QuantityNumber = Field(description="Quantity in (0 for an OUT)")
    out_quantity: QuantityNumber = Field(description="Quantity out (0 for an IN)")
    unit_cost: DecimalNumber = Field(description="Cost per base unit it moved at")
    value: DecimalNumber = Field(description="Quantity x unit cost")
    balance_quantity: QuantityNumber = Field(description="Quantity after it")
    balance_value: DecimalNumber = Field(description="Value after it")
    average_cost: DecimalNumber | None = Field(
        None, description="Balance value / balance quantity; null without stock"
    )


class KardexResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    product_id: int = Field(description="Product ID")
    product_name: str = Field(description="Product name")
    sku: str = Field(description="Product SKU")
    warehouse_id: int | None = Field(
        None, description="Warehouse it covers; null: every location"
    )
    from_date: date = Field(description="Start date (inclusive)")
    to_date: date = Field(description="End date (inclusive)")
    opening: KardexBalanceResponse = Field(description="Balance before fromDate")
    entries: list[KardexEntryResponse] = Field(
        description="Movements of the period, by date and ID"
    )
    total_in: KardexTotalResponse = Field(description="Entries of the period")
    total_out: KardexTotalResponse = Field(description="Exits of the period")
    closing: KardexBalanceResponse = Field(
        description="opening + totalIn - totalOut, in quantity and value"
    )


class KardexQueryParams(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    product_id: int = Field(ge=1, description="Product ID")
    warehouse_id: int | None = Field(
        None, ge=1, description="Warehouse (omit for every location)"
    )
    # Defaults live in GetKardexQuery, as in rotation
    from_date: date | None = Field(
        None, description="Start date (defaults to first day of current month)"
    )
    to_date: date | None = Field(None, description="End date (defaults to today)")
