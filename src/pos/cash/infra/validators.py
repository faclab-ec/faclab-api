from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.pos.cash.domain.entities import CashMovementType
from src.sales.domain.entities import PaymentMethod
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


class MethodExpectedResponse(BaseModel):
    """What a payment method should have at the count (S5.9)"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    payment_method: PaymentMethod = Field(description="Payment method to count")
    payments_total: DecimalNumber = Field(
        description="Applied payments of the shift's completed sales in this method"
    )
    customer_payments_total: DecimalNumber = Field(
        description="Payments on account taken in this method"
    )
    refunds_total: DecimalNumber = Field(
        description="Given back by the shift's completed refunds in this method"
    )
    expected: DecimalNumber = Field(
        description="Expected: for CASH the expected balance; otherwise payments + "
        "payments on account - refunds"
    )


class CashSummaryResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    shift_id: int = Field(description="Shift ID")
    opening_balance: DecimalNumber = Field(
        description="Opening balance when the shift started"
    )
    cash_sales: DecimalNumber = Field(description="Total cash received from sales")
    cash_refunds: DecimalNumber = Field(description="Total cash returned in refunds")
    customer_payments: DecimalNumber = Field(
        description="Total cash received as payments on account (S5.5)"
    )
    cash_in: DecimalNumber = Field(description="Total manual cash-in movements")
    cash_out: DecimalNumber = Field(description="Total manual cash-out movements")
    expected_balance: DecimalNumber = Field(
        description="Expected cash balance (opening + sales - refunds + payments on "
        "account + in - out)"
    )
    by_method: list[MethodExpectedResponse] = Field(
        description="What to count at the closing (S5.9): CASH always and every other "
        "method the shift moved; CREDIT is not counted"
    )
    justification_threshold: DecimalNumber = Field(
        description="A count whose difference is over this amount needs a "
        "justification (S5.9)"
    )
