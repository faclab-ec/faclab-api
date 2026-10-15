from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.pos.cash.domain.entities import CashMovementType
from src.shared.infra.validators import DecimalNumber, QueryParams


class RegisterCashMovementRequest(BaseModel):
    type: CashMovementType = Field(..., description="Cash movement direction")
    amount: DecimalNumber = Field(..., gt=0, description="Cash amount")
    reason: str | None = Field(
        None, max_length=512, description="Reason for the cash movement"
    )


class CashMovementResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int = Field(description="Cash movement ID")
    shift_id: int = Field(description="Shift ID this movement belongs to")
    type: CashMovementType = Field(description="Cash movement direction")
    amount: DecimalNumber = Field(description="Cash amount")
    reason: str | None = Field(None, description="Reason for the movement")
    performed_by: str | None = Field(
        None, description="Person who performed the movement"
    )
    created_at: datetime | None = Field(None, description="Record creation timestamp")


class CashMovementQueryParams(QueryParams):
    pass


class CashSummaryResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    shift_id: int = Field(description="Shift ID")
    opening_balance: DecimalNumber = Field(
        description="Opening balance when the shift started"
    )
    cash_sales: DecimalNumber = Field(description="Total cash received from sales")
    cash_refunds: DecimalNumber = Field(description="Total cash returned in refunds")
    cash_in: DecimalNumber = Field(description="Total manual cash-in movements")
    cash_out: DecimalNumber = Field(description="Total manual cash-out movements")
    expected_balance: DecimalNumber = Field(
        description="Expected cash balance (opening + sales - refunds + in - out)"
    )
