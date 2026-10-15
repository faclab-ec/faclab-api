from datetime import datetime
from decimal import Decimal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from src.pos.refund.domain.entities import RefundStatus
from src.sales.domain.entities import PaymentMethod
from src.shared.domain.tax import TaxCode
from src.shared.infra.validators import DecimalNumber, QueryParams


class CreateRefundItemInput(BaseModel):
    sale_item_id: int = Field(
        ...,
        gt=0,
        description="Original sale item ID to refund",
        validation_alias=AliasChoices("saleItemId", "sale_item_id"),
        serialization_alias="saleItemId",
    )
    quantity: int = Field(..., gt=0, description="Quantity to refund")


class CreateRefundRequest(BaseModel):
    original_sale_id: int = Field(
        ...,
        gt=0,
        description="Original sale ID to refund against",
        validation_alias=AliasChoices("originalSaleId", "original_sale_id"),
        serialization_alias="originalSaleId",
    )
    items: list[CreateRefundItemInput] = Field(
        ..., min_length=1, description="Items to refund (partial or total)"
    )
    reason: str | None = Field(
        None, max_length=512, description="Reason for the refund"
    )


class ProcessRefundPaymentInput(BaseModel):
    amount: Decimal = Field(..., gt=0, description="Refund payment amount")
    payment_method: PaymentMethod = Field(
        ...,
        description="Payment method for the refund",
        validation_alias=AliasChoices("paymentMethod", "payment_method"),
        serialization_alias="paymentMethod",
    )
    reference: str | None = Field(None, max_length=128, description="Payment reference")


class ProcessRefundRequest(BaseModel):
    payments: list[ProcessRefundPaymentInput] = Field(
        ...,
        min_length=1,
        description="Refund payments (total must cover the refund amount)",
    )


class RefundItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    refund_id: int = Field(
        ...,
        validation_alias=AliasChoices("refundId", "refund_id"),
        serialization_alias="refundId",
    )
    original_sale_item_id: int = Field(
        ...,
        validation_alias=AliasChoices("originalSaleItemId", "original_sale_item_id"),
        serialization_alias="originalSaleItemId",
    )
    product_id: int = Field(
        ...,
        validation_alias=AliasChoices("productId", "product_id"),
        serialization_alias="productId",
    )
    quantity: int
    unit_price: DecimalNumber = Field(
        ...,
        validation_alias=AliasChoices("unitPrice", "unit_price"),
        serialization_alias="unitPrice",
    )
    discount: DecimalNumber
    tax_code: TaxCode = Field(
        ...,
        validation_alias=AliasChoices("taxCode", "tax_code"),
        serialization_alias="taxCode",
    )
    tax_amount: DecimalNumber = Field(
        ...,
        validation_alias=AliasChoices("taxAmount", "tax_amount"),
        serialization_alias="taxAmount",
    )
    subtotal: DecimalNumber


class RefundPaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    refund_id: int = Field(
        ...,
        validation_alias=AliasChoices("refundId", "refund_id"),
        serialization_alias="refundId",
    )
    amount: DecimalNumber
    payment_method: PaymentMethod = Field(
        ...,
        description="Payment method used for the refund",
        validation_alias=AliasChoices("paymentMethod", "payment_method"),
        serialization_alias="paymentMethod",
    )
    reference: str | None
    created_at: datetime | None = Field(
        None,
        validation_alias=AliasChoices("createdAt", "created_at"),
        serialization_alias="createdAt",
    )


class RefundResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_sale_id: int = Field(
        ...,
        validation_alias=AliasChoices("originalSaleId", "original_sale_id"),
        serialization_alias="originalSaleId",
    )
    shift_id: int | None = Field(
        None,
        validation_alias=AliasChoices("shiftId", "shift_id"),
        serialization_alias="shiftId",
    )
    refund_date: datetime | None = Field(
        None,
        validation_alias=AliasChoices("refundDate", "refund_date"),
        serialization_alias="refundDate",
    )
    subtotal: DecimalNumber
    tax: DecimalNumber
    total: DecimalNumber
    reason: str | None
    status: RefundStatus = Field(description="Current refund status")
    refunded_by: str | None = Field(
        None,
        validation_alias=AliasChoices("refundedBy", "refunded_by"),
        serialization_alias="refundedBy",
    )
    created_at: datetime | None = Field(
        None,
        validation_alias=AliasChoices("createdAt", "created_at"),
        serialization_alias="createdAt",
    )


class RefundDetailResponse(RefundResponse):
    model_config = ConfigDict(from_attributes=True)

    items: list[RefundItemResponse] = []
    payments: list[RefundPaymentResponse] = []


class RefundQueryParams(QueryParams):
    sale_id: int | None = Field(None, ge=1, description="Filter by original sale ID")
    status: RefundStatus | None = Field(None, description="Filter by refund status")
