"""Pydantic schemas for Sales validation and serialization."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, computed_field

from src.sales.domain.entities import (
    InvoiceStatus,
    PaymentMethod,
    PaymentStatus,
    SaleStatus,
)
from src.shared.domain.tax import TaxCode
from src.shared.infra.validators import DecimalNumber, QuantityNumber, QueryParams


class SaleItemRequest(BaseModel):
    """Add a line item to a sale."""

    product_id: int = Field(
        ...,
        gt=0,
        description="Product ID",
        validation_alias=AliasChoices("productId", "product_id"),
        serialization_alias="productId",
    )
    quantity: QuantityNumber = Field(
        ...,
        gt=0,
        description="Quantity to sell in its presentation: the decimals of the "
        "product's unit minus those of the presentation's factor",
    )
    unit_price: Decimal | None = Field(
        None,
        gt=0,
        description="Price of one unit of its presentation (one box). None: the "
        "price of its list (the customer's, the branch's or the general one, "
        "S5.3). Another price is an override: it needs overrideReason",
        validation_alias=AliasChoices("unitPrice", "unit_price"),
        serialization_alias="unitPrice",
    )
    discount: Decimal = Field(
        Decimal("0"), ge=0, le=100, description="Discount percentage (0-100)"
    )
    presentation_id: int | None = Field(
        None,
        gt=0,
        description="Presentation it is sold in (box of 100); none: the base unit. "
        "Stock moves quantity × its factor",
        validation_alias=AliasChoices("presentationId", "presentation_id"),
        serialization_alias="presentationId",
    )
    override_reason: str | None = Field(
        None,
        max_length=512,
        description="Why it is sold at a price other than its list's "
        "(OVERRIDE_REASON_REQUIRED without it); recorded in the audit log",
        validation_alias=AliasChoices("overrideReason", "override_reason"),
        serialization_alias="overrideReason",
    )


class SaleItemUpdateRequest(BaseModel):
    """Update an existing sale line item."""

    quantity: QuantityNumber | None = Field(None, gt=0, description="New quantity")
    discount: Decimal | None = Field(
        None, ge=0, le=100, description="New discount percentage (0-100)"
    )


class SaleRequest(BaseModel):
    """Create a new sale in DRAFT status."""

    customer_id: int | None = Field(
        None,
        gt=0,
        description="Customer ID (optional for final consumers)",
        validation_alias=AliasChoices("customerId", "customer_id"),
        serialization_alias="customerId",
    )
    is_final_consumer: bool = Field(
        False,
        description="Whether this is a final consumer (anonymous) sale",
        validation_alias=AliasChoices("isFinalConsumer", "is_final_consumer"),
        serialization_alias="isFinalConsumer",
    )
    notes: str | None = Field(None, max_length=512, description="Additional notes")


class PaymentRequest(BaseModel):
    """Register a payment against a sale."""

    amount: Decimal = Field(
        ...,
        gt=0,
        description=(
            "Amount the customer hands over. The sale takes what it still owes; "
            "the rest of a cash payment is the change, and any other method "
            "cannot exceed the balance"
        ),
    )
    payment_method: PaymentMethod = Field(
        ...,
        description="Payment method",
        validation_alias=AliasChoices("paymentMethod", "payment_method"),
        serialization_alias="paymentMethod",
    )
    reference: str | None = Field(
        None, max_length=128, description="Payment reference (e.g. transaction ID)"
    )
    notes: str | None = Field(None, max_length=512, description="Payment notes")


class CancelSaleRequest(BaseModel):
    """Cancel a sale."""

    reason: str | None = Field(None, max_length=512, description="Cancellation reason")


class SaleItemResponse(BaseModel):
    """Sale line item details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    sale_id: int = Field(
        ...,
        validation_alias=AliasChoices("saleId", "sale_id"),
        serialization_alias="saleId",
    )
    product_id: int = Field(
        ...,
        validation_alias=AliasChoices("productId", "product_id"),
        serialization_alias="productId",
    )
    product_name: str | None = Field(
        None,
        description="Product name",
        validation_alias=AliasChoices("productName", "product_name"),
        serialization_alias="productName",
    )
    product_sku: str | None = Field(
        None,
        description="Product SKU",
        validation_alias=AliasChoices("productSku", "product_sku"),
        serialization_alias="productSku",
    )
    quantity: QuantityNumber = Field(description="Quantity in its presentation")
    presentation_id: int | None = Field(
        None,
        description="Presentation it is sold in (null in lines from before S5.2, "
        "in base units)",
        validation_alias=AliasChoices("presentationId", "presentation_id"),
        serialization_alias="presentationId",
    )
    presentation_name: str | None = Field(
        None,
        description="Name of its presentation (Caja x100)",
        validation_alias=AliasChoices("presentationName", "presentation_name"),
        serialization_alias="presentationName",
    )
    unit_factor: QuantityNumber = Field(
        Decimal(1),
        description="Base units in one of its presentation, copied when it was added",
        validation_alias=AliasChoices("unitFactor", "unit_factor"),
        serialization_alias="unitFactor",
    )
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
    price_override: DecimalNumber | None = Field(
        None,
        validation_alias=AliasChoices("priceOverride", "price_override"),
        serialization_alias="priceOverride",
    )
    override_reason: str | None = Field(
        None,
        validation_alias=AliasChoices("overrideReason", "override_reason"),
        serialization_alias="overrideReason",
    )

    @computed_field(alias="baseQuantity")
    @property
    def base_quantity(self) -> QuantityNumber:
        """Quantity in base units, the one stock moved: quantity × unitFactor"""
        return self.quantity * self.unit_factor


class PaymentResponse(BaseModel):
    """Payment record details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    sale_id: int = Field(
        ...,
        validation_alias=AliasChoices("saleId", "sale_id"),
        serialization_alias="saleId",
    )
    amount: DecimalNumber = Field(
        ...,
        description="Applied to the sale (what the customer handed over minus the change)",
    )
    amount_tendered: DecimalNumber = Field(
        ...,
        description="What the customer handed over",
        validation_alias=AliasChoices("amountTendered", "amount_tendered"),
        serialization_alias="amountTendered",
    )
    change: DecimalNumber = Field(..., description="Given back (cash only)")
    payment_method: PaymentMethod = Field(
        ...,
        description="Payment method used",
        validation_alias=AliasChoices("paymentMethod", "payment_method"),
        serialization_alias="paymentMethod",
    )
    payment_date: datetime | None = Field(
        None,
        validation_alias=AliasChoices("paymentDate", "payment_date"),
        serialization_alias="paymentDate",
    )
    reference: str | None
    notes: str | None
    term_days: int | None = Field(
        None,
        description="Days the customer has to pay a CREDIT payment (S5.5)",
        validation_alias=AliasChoices("termDays", "term_days"),
        serialization_alias="termDays",
    )
    created_at: datetime | None = Field(
        None,
        validation_alias=AliasChoices("createdAt", "created_at"),
        serialization_alias="createdAt",
    )


class SaleResponse(BaseModel):
    """Sale resource details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int | None = Field(
        None,
        validation_alias=AliasChoices("customerId", "customer_id"),
        serialization_alias="customerId",
    )
    customer_name: str | None = Field(
        None,
        description="Customer name (null for final consumers)",
        validation_alias=AliasChoices("customerName", "customer_name"),
        serialization_alias="customerName",
    )
    is_final_consumer: bool = Field(
        False,
        validation_alias=AliasChoices("isFinalConsumer", "is_final_consumer"),
        serialization_alias="isFinalConsumer",
    )
    shift_id: int | None = Field(
        None,
        validation_alias=AliasChoices("shiftId", "shift_id"),
        serialization_alias="shiftId",
    )
    branch_id: int | None = Field(
        None,
        description="Branch of the sale (null in sales from before S2.6)",
        validation_alias=AliasChoices("branchId", "branch_id"),
        serialization_alias="branchId",
    )
    emission_point_id: int | None = Field(
        None,
        description="Emission point of the POS terminal",
        validation_alias=AliasChoices("emissionPointId", "emission_point_id"),
        serialization_alias="emissionPointId",
    )
    terminal_id: int | None = Field(
        None,
        description="POS terminal of the sale",
        validation_alias=AliasChoices("terminalId", "terminal_id"),
        serialization_alias="terminalId",
    )
    quote_id: int | None = Field(
        None,
        description="Quote the sale converted (S5.4), when it was charged from one",
        validation_alias=AliasChoices("quoteId", "quote_id"),
        serialization_alias="quoteId",
    )
    number: str | None = Field(
        None,
        description="Document number, correlative per branch (`V-001-000123`), "
        "given when the sale is confirmed",
    )
    status: SaleStatus = Field(description="Current sale status")
    sale_date: datetime | None = Field(
        None,
        validation_alias=AliasChoices("saleDate", "sale_date"),
        serialization_alias="saleDate",
    )
    subtotal: DecimalNumber
    tax: DecimalNumber
    discount: DecimalNumber
    discount_type: Literal["PERCENTAGE", "AMOUNT"] | None = Field(
        None,
        description="Type of discount applied to the sale",
        validation_alias=AliasChoices("discountType", "discount_type"),
        serialization_alias="discountType",
    )
    discount_value: DecimalNumber = Field(
        Decimal("0"),
        validation_alias=AliasChoices("discountValue", "discount_value"),
        serialization_alias="discountValue",
    )
    total: DecimalNumber
    payment_status: PaymentStatus = Field(
        ...,
        description="Current payment status",
        validation_alias=AliasChoices("paymentStatus", "payment_status"),
        serialization_alias="paymentStatus",
    )
    notes: str | None
    created_by: str | None = Field(
        None,
        validation_alias=AliasChoices("createdBy", "created_by"),
        serialization_alias="createdBy",
    )
    parked_at: datetime | None = Field(
        None,
        validation_alias=AliasChoices("parkedAt", "parked_at"),
        serialization_alias="parkedAt",
    )
    park_reason: str | None = Field(
        None,
        validation_alias=AliasChoices("parkReason", "park_reason"),
        serialization_alias="parkReason",
    )
    invoice_status: InvoiceStatus | None = Field(
        None,
        description="Electronic invoice of a confirmed sale: PENDING while the SRI "
        "answers, AUTHORIZED or REJECTED; null if it was never sent",
        validation_alias=AliasChoices("invoiceStatus", "invoice_status"),
        serialization_alias="invoiceStatus",
    )
    invoice_id: str | None = Field(
        None,
        description="Id in faclab-invoicing of the last invoice with a result "
        "(authorized or rejected)",
        validation_alias=AliasChoices("invoiceId", "invoice_id"),
        serialization_alias="invoiceId",
    )
    invoice_rejection_reason: str | None = Field(
        None,
        description="Why the SRI rejected the invoice (its messages), while it "
        "is REJECTED",
        validation_alias=AliasChoices(
            "invoiceRejectionReason", "invoice_rejection_reason"
        ),
        serialization_alias="invoiceRejectionReason",
    )
    invoice_requested_at: datetime | None = Field(
        None,
        description="When the sale was last sent to faclab-invoicing (confirmed "
        "or resent)",
        validation_alias=AliasChoices("invoiceRequestedAt", "invoice_requested_at"),
        serialization_alias="invoiceRequestedAt",
    )
    created_at: datetime | None = Field(
        None,
        validation_alias=AliasChoices("createdAt", "created_at"),
        serialization_alias="createdAt",
    )
    updated_at: datetime | None = Field(
        None,
        validation_alias=AliasChoices("updatedAt", "updated_at"),
        serialization_alias="updatedAt",
    )


class SaleDetailResponse(SaleResponse):
    """Sale with items and payments included."""

    model_config = ConfigDict(from_attributes=True)

    items: list[SaleItemResponse] = []
    payments: list[PaymentResponse] = []


# Query Params
class SaleQueryParams(QueryParams):
    customer_id: int | None = Field(None, ge=1, description="Filter by customer ID")
    status: SaleStatus | None = Field(None, description="Filter by sale status")
    invoice_status: InvoiceStatus | None = Field(
        None, description="Filter by the status of the sale's invoice"
    )
