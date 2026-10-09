from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.inventory.adjustment.domain.entities import AdjustmentReason, AdjustmentStatus
from src.shared.infra.validators import QueryParams


class CreateAdjustmentRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    warehouse_id: int = Field(description="ID of the warehouse being adjusted")
    reason: AdjustmentReason = Field(description="Reason for the adjustment")
    notes: str | None = Field(None, description="Additional notes")
    adjusted_by: str | None = Field(
        None, description="Name of the person performing the adjustment"
    )


class UpdateAdjustmentRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    notes: str | None = Field(None, description="Additional notes")
    adjusted_by: str | None = Field(
        None, description="Name of the person performing the adjustment"
    )


class AddAdjustmentItemRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    product_id: int = Field(description="Product ID to adjust")
    location_id: int = Field(description="Storage location ID")
    actual_quantity: int = Field(description="Actual counted quantity")
    lot_id: int | None = Field(None, description="Lot ID (if applicable)")
    notes: str | None = Field(None, description="Notes for this item")


class UpdateAdjustmentItemRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    actual_quantity: int | None = Field(None, description="Corrected actual quantity")
    notes: str | None = Field(None, description="Updated notes")


class AdjustmentResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int = Field(description="Adjustment ID")
    warehouse_id: int = Field(description="Warehouse ID")
    reason: AdjustmentReason = Field(description="Reason for the adjustment")
    status: AdjustmentStatus = Field(description="Current adjustment status")
    adjustment_date: datetime | None = Field(None, description="Date of the adjustment")
    notes: str | None = Field(None, description="Additional notes")
    adjusted_by: str | None = Field(
        None, description="Person who performed the adjustment"
    )
    created_at: datetime | None = Field(None, description="Record creation timestamp")


class AdjustmentItemResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int = Field(description="Adjustment item ID")
    adjustment_id: int = Field(description="Parent adjustment ID")
    product_id: int = Field(description="Product ID")
    product_name: str | None = Field(None, description="Product name")
    product_sku: str | None = Field(None, description="Product SKU")
    location_id: int = Field(description="Storage location ID")
    expected_quantity: int = Field(
        description="System-recorded quantity before adjustment"
    )
    actual_quantity: int = Field(description="Actual counted quantity")
    difference: int = Field(description="Difference (actual - expected)")
    lot_id: int | None = Field(None, description="Lot ID (if applicable)")
    notes: str | None = Field(None, description="Notes for this item")


class AdjustmentQueryParams(QueryParams):
    status: AdjustmentStatus | None = Field(
        None, description="Filter by adjustment status"
    )
    warehouse_id: int | None = Field(None, ge=1, description="Filter by warehouse ID")
