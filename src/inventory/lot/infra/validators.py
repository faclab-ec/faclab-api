from datetime import date, datetime

from pydantic import AliasChoices, BaseModel, Field

from src.shared.infra.validators import QuantityNumber, QueryParams


class LotRequest(BaseModel):
    product_id: int = Field(
        ...,
        ge=1,
        description="Product ID",
        validation_alias=AliasChoices("productId", "product_id"),
        serialization_alias="productId",
    )
    lot_number: str = Field(
        ...,
        max_length=64,
        description="Lot number",
        validation_alias=AliasChoices("lotNumber", "lot_number"),
        serialization_alias="lotNumber",
    )
    initial_quantity: QuantityNumber = Field(
        ...,
        gt=0,
        description="Initial quantity in this lot, with the decimals of the "
        "product's unit",
        validation_alias=AliasChoices("initialQuantity", "initial_quantity"),
        serialization_alias="initialQuantity",
    )
    manufacture_date: date | None = Field(
        None,
        description="Manufacture date",
        validation_alias=AliasChoices("manufactureDate", "manufacture_date"),
        serialization_alias="manufactureDate",
    )
    expiration_date: date | None = Field(
        None,
        description="Expiration date",
        validation_alias=AliasChoices("expirationDate", "expiration_date"),
        serialization_alias="expirationDate",
    )
    notes: str | None = Field(None, max_length=1024)


class LotUpdateRequest(BaseModel):
    current_quantity: QuantityNumber | None = Field(
        None,
        ge=0,
        description="Current quantity in this lot",
        validation_alias=AliasChoices("currentQuantity", "current_quantity"),
        serialization_alias="currentQuantity",
    )
    manufacture_date: date | None = Field(
        None,
        description="Manufacture date",
        validation_alias=AliasChoices("manufactureDate", "manufacture_date"),
        serialization_alias="manufactureDate",
    )
    expiration_date: date | None = Field(
        None,
        description="Expiration date",
        validation_alias=AliasChoices("expirationDate", "expiration_date"),
        serialization_alias="expirationDate",
    )
    notes: str | None = Field(None, max_length=1024)


class LotResponse(BaseModel):
    id: int = Field(ge=1)
    product_id: int = Field(
        ge=1,
        validation_alias=AliasChoices("productId", "product_id"),
        serialization_alias="productId",
    )
    lot_number: str = Field(
        validation_alias=AliasChoices("lotNumber", "lot_number"),
        serialization_alias="lotNumber",
    )
    manufacture_date: date | None = Field(
        None,
        validation_alias=AliasChoices("manufactureDate", "manufacture_date"),
        serialization_alias="manufactureDate",
    )
    expiration_date: date | None = Field(
        None,
        validation_alias=AliasChoices("expirationDate", "expiration_date"),
        serialization_alias="expirationDate",
    )
    initial_quantity: QuantityNumber = Field(
        validation_alias=AliasChoices("initialQuantity", "initial_quantity"),
        serialization_alias="initialQuantity",
    )
    current_quantity: QuantityNumber = Field(
        validation_alias=AliasChoices("currentQuantity", "current_quantity"),
        serialization_alias="currentQuantity",
    )
    is_expired: bool = Field(
        validation_alias=AliasChoices("isExpired", "is_expired"),
        serialization_alias="isExpired",
    )
    days_to_expiry: int | None = Field(
        None,
        validation_alias=AliasChoices("daysToExpiry", "days_to_expiry"),
        serialization_alias="daysToExpiry",
    )
    notes: str | None = None
    created_at: datetime | None = Field(
        None,
        validation_alias=AliasChoices("createdAt", "created_at"),
        serialization_alias="createdAt",
    )


# Query Params
class LotQueryParams(QueryParams):
    product_id: int | None = Field(None, ge=1)
    expiring_in_days: int | None = Field(None, ge=1)
