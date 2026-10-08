from pydantic import AliasChoices, BaseModel, Field

from src.shared.infra.validators import QueryParams


class StockResponse(BaseModel):
    id: int = Field(description="Stock record ID")
    product_id: int = Field(
        ...,
        ge=1,
        description="Product ID",
        validation_alias=AliasChoices("productId", "product_id"),
        serialization_alias="productId",
    )
    product_name: str | None = Field(
        None,
        description="Product name",
        validation_alias=AliasChoices("productName", "product_name"),
        serialization_alias="productName",
    )
    quantity: int = Field(description="Current stock quantity on hand")
    location_id: int | None = Field(
        None,
        description="Storage location ID",
        validation_alias=AliasChoices("locationId", "location_id"),
        serialization_alias="locationId",
    )
    location_name: str | None = Field(
        None,
        description="Storage location name",
        validation_alias=AliasChoices("locationName", "location_name"),
        serialization_alias="locationName",
    )
    reserved_quantity: int = Field(
        0,
        description="Quantity reserved for confirmed transfers or orders",
        validation_alias=AliasChoices("reservedQuantity", "reserved_quantity"),
        serialization_alias="reservedQuantity",
    )


class StockQueryParams(QueryParams):
    product_id: int | None = Field(None, ge=1, description="Filter by product ID")
    location_id: int | None = Field(None, ge=1, description="Filter by location ID")
