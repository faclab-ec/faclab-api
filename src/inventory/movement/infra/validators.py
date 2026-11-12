from datetime import datetime
from decimal import Decimal

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.domain.exceptions import InvalidMovementTypeError
from src.shared.infra.precision import MONEY_PRECISION, MONEY_SCALE
from src.shared.infra.validators import DecimalNumber, QuantityNumber, QueryParams


class MovementBase(BaseModel):
    product_id: int = Field(
        ...,
        ge=1,
        description="Product ID",
        validation_alias=AliasChoices("productId", "product_id"),
        serialization_alias="productId",
    )
    quantity: QuantityNumber = Field(
        ...,
        description="Quantity: positive for IN, negative for OUT. Takes the "
        "decimals of the product's unit of measure",
    )
    type: MovementType
    location_id: int | None = Field(
        None,
        validation_alias=AliasChoices("locationId", "location_id"),
        serialization_alias="locationId",
    )
    reason: str | None = None
    date: datetime | None = None


class MovementRequest(MovementBase):
    unit_cost: Decimal | None = Field(
        None,
        ge=0,
        max_digits=MONEY_PRECISION,
        decimal_places=MONEY_SCALE,
        description="Cost per base unit, only for an IN (e.g. an initial balance). "
        "Without it the IN enters at the location's average cost; an OUT always "
        "leaves at that average",
        validation_alias=AliasChoices("unitCost", "unit_cost"),
        serialization_alias="unitCost",
    )

    @field_validator("quantity", mode="after")
    @classmethod
    def validate_quantity_not_zero(cls, v):
        if v == 0:
            raise InvalidMovementTypeError("La cantidad no puede ser cero")
        return v

    @model_validator(mode="after")
    def validate_quantity_by_movement_type(self) -> "MovementRequest":
        if self.type == MovementType.IN and self.quantity < 0:
            raise InvalidMovementTypeError(
                "La cantidad debe ser positiva para movimientos de entrada"
            )
        elif self.type == MovementType.OUT and self.quantity > 0:
            raise InvalidMovementTypeError(
                "La cantidad debe ser negativa para movimientos de salida"
            )
        if self.type == MovementType.OUT and self.unit_cost is not None:
            raise InvalidMovementTypeError(
                "El costo unitario solo aplica a entradas: una salida sale al "
                "costo promedio de la ubicación"
            )
        return self


class MovementResponse(MovementBase):
    id: int
    # The document that moved the stock (sale, refund, adjustment, transfer,
    # purchase order). Only those flows set it: a manual movement has none
    reference_type: str | None = Field(
        None,
        validation_alias=AliasChoices("referenceType", "reference_type"),
        serialization_alias="referenceType",
    )
    reference_id: int | None = Field(
        None,
        validation_alias=AliasChoices("referenceId", "reference_id"),
        serialization_alias="referenceId",
    )
    unit_cost: DecimalNumber = Field(
        description="Cost per base unit it moved at: an IN's own cost, an OUT "
        "the average of its location",
        validation_alias=AliasChoices("unitCost", "unit_cost"),
        serialization_alias="unitCost",
    )


class MovementQueryParams(QueryParams):
    product_id: int | None = Field(None, ge=1)
    type: MovementType | None = None
    from_date: datetime | None = None
    to_date: datetime | None = None
