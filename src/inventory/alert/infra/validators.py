from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.inventory.alert.domain.types import AlertType
from src.shared.infra.validators import QuantityNumber


class StockAlertResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    type: AlertType = Field(description="Type of stock alert")
    product_id: int = Field(description="Product ID")
    product_name: str = Field(description="Product name")
    sku: str = Field(description="Product SKU")
    current_quantity: QuantityNumber = Field(description="Current stock quantity")
    threshold: QuantityNumber = Field(description="Alert threshold that was breached")
    warehouse_id: int | None = Field(
        None, description="Warehouse ID (if location-specific)"
    )
    lot_id: int | None = Field(None, description="Lot ID (for expiration alerts)")
    days_to_expiry: int | None = Field(
        None, description="Days until expiration (for expiring lots)"
    )


class StockAlertQueryParams(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    warehouse_id: int | None = Field(None, ge=1, description="Filter by warehouse ID")


class ExpiringLotsQueryParams(BaseModel):
    days: int = Field(
        30, ge=1, description="Number of days to look ahead for expiring lots"
    )
