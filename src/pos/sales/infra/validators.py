"""Pydantic schemas for POS Sales validation and serialization."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from src.sales.domain.entities import PaymentMethod, SaleStatus
from src.shared.domain.tax import TaxCode
from src.shared.infra.validators import DecimalNumber


class ParkSaleRequest(BaseModel):
    """Park (hold) a sale for later."""

    reason: str | None = Field(
        None, max_length=512, description="Reason for parking the sale"
    )


class ApplyDiscountRequest(BaseModel):
    """Apply a discount to an entire sale."""

    discount_type: Literal["PERCENTAGE", "AMOUNT"] = Field(
        ...,
        description="Discount type: PERCENTAGE (percentage off) or AMOUNT (fixed amount off)",
        validation_alias=AliasChoices("discountType", "discount_type"),
        serialization_alias="discountType",
    )
    discount_value: Decimal = Field(
        ...,
        ge=0,
        description="Discount value (percentage or fixed amount depending on discountType)",
        validation_alias=AliasChoices("discountValue", "discount_value"),
        serialization_alias="discountValue",
    )


class OverridePriceRequest(BaseModel):
    """Override the price of a sale item (requires a reason)."""

    new_price: Decimal = Field(
        ...,
        gt=0,
        validation_alias=AliasChoices("newPrice", "new_price"),
        serialization_alias="newPrice",
    )
    reason: str = Field(..., min_length=1, max_length=512)


class POSSaleRequest(BaseModel):
    """Create a new POS sale in DRAFT status."""

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


class QuickSaleItemInput(BaseModel):
    """Line item for a quick sale."""

    product_id: int = Field(
        ...,
        gt=0,
        description="Product ID",
        validation_alias=AliasChoices("productId", "product_id"),
        serialization_alias="productId",
    )
    quantity: int = Field(..., gt=0, description="Quantity to sell")
    unit_price: Decimal | None = Field(
        None,
        gt=0,
        description="Unit price override (uses product sale price if omitted)",
        validation_alias=AliasChoices("unitPrice", "unit_price"),
        serialization_alias="unitPrice",
    )
    discount: Decimal = Field(
        Decimal("0"), ge=0, le=100, description="Discount percentage (0-100)"
    )
    override_reason: str | None = Field(
        None,
        min_length=1,
        max_length=512,
        description="Why unitPrice differs from the product price (required then)",
        validation_alias=AliasChoices("overrideReason", "override_reason"),
        serialization_alias="overrideReason",
    )


class QuickSalePaymentInput(BaseModel):
    """Payment for a quick sale."""

    amount: Decimal = Field(..., gt=0, description="Payment amount")
    payment_method: PaymentMethod = Field(
        ...,
        description="Payment method",
        validation_alias=AliasChoices("paymentMethod", "payment_method"),
        serialization_alias="paymentMethod",
    )
    reference: str | None = Field(None, max_length=128, description="Payment reference")


class QuickSaleRequest(BaseModel):
    """Complete checkout in a single request — creates sale, adds items, registers payments, and confirms."""

    customer_id: int | None = Field(
        None,
        gt=0,
        description="Customer ID (final consumer if omitted)",
        validation_alias=AliasChoices("customerId", "customer_id"),
        serialization_alias="customerId",
    )
    items: list[QuickSaleItemInput] = Field(
        ..., min_length=1, description="Line items for the sale"
    )
    payments: list[QuickSalePaymentInput] = Field(
        ..., min_length=1, description="Payments (total must cover the sale amount)"
    )
    discount_type: Literal["PERCENTAGE", "AMOUNT"] | None = Field(
        None,
        description="Sale-level discount type; omit for no discount",
        validation_alias=AliasChoices("discountType", "discount_type"),
        serialization_alias="discountType",
    )
    discount_value: Decimal = Field(
        Decimal("0"),
        ge=0,
        description="Discount value (percentage or fixed amount depending on discountType)",
        validation_alias=AliasChoices("discountValue", "discount_value"),
        serialization_alias="discountValue",
    )
    notes: str | None = Field(None, max_length=512, description="Additional notes")


class ReceiptItemResponse(BaseModel):
    """Line item in a receipt."""

    model_config = ConfigDict(from_attributes=True)

    product_name: str = Field(
        ...,
        validation_alias=AliasChoices("productName", "product_name"),
        serialization_alias="productName",
    )
    quantity: int
    unit_price: DecimalNumber = Field(
        ...,
        validation_alias=AliasChoices("unitPrice", "unit_price"),
        serialization_alias="unitPrice",
    )
    discount: DecimalNumber
    discount_amount: DecimalNumber = Field(
        ...,
        validation_alias=AliasChoices("discountAmount", "discount_amount"),
        serialization_alias="discountAmount",
    )
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


class TaxBreakdownResponse(BaseModel):
    """Tax breakdown by VAT code."""

    model_config = ConfigDict(from_attributes=True)

    tax_code: TaxCode = Field(
        ...,
        validation_alias=AliasChoices("taxCode", "tax_code"),
        serialization_alias="taxCode",
    )
    tax_rate: DecimalNumber = Field(
        ...,
        validation_alias=AliasChoices("taxRate", "tax_rate"),
        serialization_alias="taxRate",
    )
    taxable_base: DecimalNumber = Field(
        ...,
        validation_alias=AliasChoices("taxableBase", "taxable_base"),
        serialization_alias="taxableBase",
    )
    tax_amount: DecimalNumber = Field(
        ...,
        validation_alias=AliasChoices("taxAmount", "tax_amount"),
        serialization_alias="taxAmount",
    )


class ReceiptPaymentResponse(BaseModel):
    """Payment entry in a receipt."""

    model_config = ConfigDict(from_attributes=True)

    method: str
    amount: DecimalNumber
    reference: str | None = None


class CustomerReceiptResponse(BaseModel):
    """Customer info on a receipt."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    tax_id: str = Field(
        ...,
        validation_alias=AliasChoices("taxId", "tax_id"),
        serialization_alias="taxId",
    )
    address: str | None = None


class BranchReceiptResponse(BaseModel):
    """Branch (SRI establishment) that issued a receipt."""

    model_config = ConfigDict(from_attributes=True)

    establishment_code: str = Field(
        ...,
        validation_alias=AliasChoices("establishmentCode", "establishment_code"),
        serialization_alias="establishmentCode",
    )
    name: str
    address: str | None = None


class TerminalReceiptResponse(BaseModel):
    """POS terminal of a receipt."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str


class ReceiptResponse(BaseModel):
    """Full receipt for a confirmed sale, including items, tax breakdown, and payments."""

    model_config = ConfigDict(from_attributes=True)

    sale_id: int = Field(
        ...,
        validation_alias=AliasChoices("saleId", "sale_id"),
        serialization_alias="saleId",
    )
    number: str | None = Field(
        None,
        description="Document number, correlative per branch (null in a draft)",
    )
    branch: BranchReceiptResponse | None = Field(
        None, description="Branch of the sale (null for sales before S2.6)"
    )
    terminal: TerminalReceiptResponse | None = None
    sale_date: datetime | None = Field(
        None,
        validation_alias=AliasChoices("saleDate", "sale_date"),
        serialization_alias="saleDate",
    )
    status: SaleStatus = Field(description="Current sale status")
    cashier: str | None = Field(
        None, description="Authenticated user who made the sale"
    )
    customer: CustomerReceiptResponse | None = None
    is_final_consumer: bool = Field(
        ...,
        validation_alias=AliasChoices("isFinalConsumer", "is_final_consumer"),
        serialization_alias="isFinalConsumer",
    )
    items: list[ReceiptItemResponse]
    tax_breakdown: list[TaxBreakdownResponse] = Field(
        ...,
        validation_alias=AliasChoices("taxBreakdown", "tax_breakdown"),
        serialization_alias="taxBreakdown",
    )
    subtotal: DecimalNumber
    discount: DecimalNumber
    discount_type: Literal["PERCENTAGE", "AMOUNT"] | None = Field(
        None,
        description="Discount type applied to the sale",
        validation_alias=AliasChoices("discountType", "discount_type"),
        serialization_alias="discountType",
    )
    discount_value: DecimalNumber = Field(
        ...,
        validation_alias=AliasChoices("discountValue", "discount_value"),
        serialization_alias="discountValue",
    )
    tax: DecimalNumber
    total: DecimalNumber
    payments: list[ReceiptPaymentResponse]
    total_paid: DecimalNumber = Field(
        ...,
        validation_alias=AliasChoices("totalPaid", "total_paid"),
        serialization_alias="totalPaid",
    )
    change: DecimalNumber
