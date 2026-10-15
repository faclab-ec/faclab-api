from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.inventory.transfer.domain.entities import TransferStatus
from src.shared.infra.validators import QueryParams


class CreateTransferRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    source_location_id: int = Field(description="Source location ID")
    destination_location_id: int = Field(description="Destination location ID")
    notes: str | None = Field(None, description="Additional notes")


class UpdateTransferRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    notes: str | None = Field(None, description="Updated notes")


class AddTransferItemRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    product_id: int = Field(description="Product ID to transfer")
    quantity: int = Field(gt=0, description="Quantity to transfer")
    lot_id: int | None = Field(None, description="Lot ID (if applicable)")
    notes: str | None = Field(None, description="Notes for this item")


class UpdateTransferItemRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    quantity: int | None = Field(None, gt=0, description="Updated quantity")
    notes: str | None = Field(None, description="Updated notes")


class TransferResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int = Field(description="Transfer ID")
    source_location_id: int = Field(description="Source location ID")
    destination_location_id: int = Field(description="Destination location ID")
    status: TransferStatus = Field(description="Current transfer status")
    transfer_date: datetime | None = Field(None, description="Date of the transfer")
    requested_by: str | None = Field(
        None, description="Person who requested the transfer"
    )
    notes: str | None = Field(None, description="Additional notes")
    created_at: datetime | None = Field(None, description="Record creation timestamp")


class TransferItemResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int = Field(description="Transfer item ID")
    transfer_id: int = Field(description="Parent transfer ID")
    product_id: int = Field(description="Product ID")
    product_name: str | None = Field(None, description="Product name")
    product_sku: str | None = Field(None, description="Product SKU")
    quantity: int = Field(description="Quantity to transfer")
    lot_id: int | None = Field(None, description="Lot ID (if applicable)")
    notes: str | None = Field(None, description="Notes for this item")


class TransferQueryParams(QueryParams):
    status: TransferStatus | None = Field(None, description="Filter by transfer status")
    source_location_id: int | None = Field(
        None, ge=1, description="Filter by source location ID"
    )
