from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from src.public_api.infra.schemas.base import Id, PublicInput, PublicModel, SyncParams
from src.public_api.infra.types import (
    Money,
    MoneyInput,
    Percent,
    PercentInput,
    Quantity,
    QuantityInput,
    Timestamp,
)
from src.sales.domain.entities import (
    InvoiceStatus,
    PaymentStatus,
    SaleChannel,
    SaleStatus,
)
from src.shared.domain.tax import TaxCode


class ApiPaymentMethod(StrEnum):
    """How a sale of the API was paid: online, outside any cash drawer"""

    CREDIT_CARD = "CREDIT_CARD"
    DEBIT_CARD = "DEBIT_CARD"
    TRANSFER = "TRANSFER"
    OTHER = "OTHER"


class SaleItem(PublicModel):
    id: int
    product_id: int
    presentation_id: int | None = None
    presentation_name: str | None = None
    quantity: Quantity = Field(description="In its presentation")
    unit_factor: Quantity = Field(description="Base units in one of its presentation")
    base_quantity: Quantity = Field(description="What left the stock")
    unit_price: Money
    discount_percent: Percent = Field(validation_alias="discount")
    tax_code: TaxCode
    tax_amount: Money
    subtotal: Money = Field(description="Before VAT, after its discount")


class SalePayment(PublicModel):
    method: str = Field(
        validation_alias="payment_method",
        description="CASH, CREDIT_CARD, DEBIT_CARD, TRANSFER, CREDIT or OTHER",
    )
    amount: Money = Field(description="What it applied to the sale")
    reference: str | None = None


class Sale(PublicModel):
    id: int
    number: str | None = Field(None, description="Of its branch: V-001-000123")
    channel: SaleChannel
    external_reference: str | None = None
    status: SaleStatus
    branch_id: int | None = None
    emission_point_id: int | None = None
    customer_id: int | None = Field(None, description="None: the final consumer")
    sale_date: Timestamp | None = None
    subtotal: Money
    tax: Money
    discount: Money
    total: Money
    payment_status: PaymentStatus
    invoice_status: InvoiceStatus | None = Field(
        None,
        description=(
            "PENDING while faclab-invoicing has it, AUTHORIZED, REJECTED or "
            "CREDITED; none if it was never sent"
        ),
    )
    invoice_id: str | None = Field(None, description="Its invoice in /invoices")
    items: list[SaleItem]
    payments: list[SalePayment]
    created_at: Timestamp
    updated_at: Timestamp


class SaleCustomerInput(PublicInput):
    """The customer by its id or by its identification, one of them"""

    id: Id | None = None
    identification: str | None = Field(None, max_length=32)

    @model_validator(mode="after")
    def _one(self) -> "SaleCustomerInput":
        if (self.id is None) == (self.identification is None):
            raise ValueError("send either the customer's id or its identification")
        return self


class SaleItemInput(PublicInput):
    product_id: Id
    presentation_id: Id | None = Field(None, description="The base unit by default")
    quantity: QuantityInput
    unit_price: MoneyInput | None = Field(
        None,
        description=(
            "Without it, the price its lists give (the customer's, the branch's "
            "or the general one); another one needs `overrideReason`"
        ),
    )
    override_reason: str | None = Field(None, max_length=255)
    discount_percent: PercentInput | None = Field(
        None, description="Discount of the line, in percent"
    )


class SalePaymentInput(PublicInput):
    method: ApiPaymentMethod
    amount: MoneyInput
    reference: str | None = Field(
        None, max_length=128, description="The payment gateway's transaction"
    )


class SaleInput(PublicInput):
    emission_point_id: Id = Field(description="Of the branch in X-Branch-Id")
    location_id: Id = Field(description="Where its stock leaves from, of the branch")
    external_reference: str | None = Field(
        None, max_length=100, description="The order in the integrator's system"
    )
    customer: SaleCustomerInput | None = Field(
        None, description="Without it, the final consumer"
    )
    items: list[SaleItemInput] = Field(min_length=1)
    payments: list[SalePaymentInput] = Field(
        min_length=1, description="They must add up to the total exactly"
    )
    notes: str | None = Field(None, max_length=512)


class CancelSaleInput(PublicInput):
    reason: str | None = Field(None, max_length=255)


class SaleListParams(SyncParams):
    branch_id: Id | None = None
    status: SaleStatus | None = None
    invoice_status: InvoiceStatus | None = None
    channel: SaleChannel | None = None
    external_reference: str | None = None
    from_: datetime | None = Field(
        None, alias="from", description="Sold at or after (ISO 8601)"
    )
    to: datetime | None = Field(None, description="Sold before (ISO 8601)")
