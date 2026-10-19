import datetime as dt

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.shared.infra.validators import DecimalNumber

# ---------------------------------------------------------------------------
# Shared sub-models
# ---------------------------------------------------------------------------


class PaymentMethodDetail(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    payment_method: str = Field(description="Payment method name")
    count: int = Field(description="Number of transactions using this method")
    total: DecimalNumber = Field(description="Total amount for this method")


class ItemSoldDetail(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    product_name: str = Field(description="Product name")
    sku: str = Field(description="Product SKU")
    quantity: int = Field(description="Total quantity sold")
    total: DecimalNumber = Field(description="Total revenue for this product")


class ShiftInfo(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int = Field(description="Shift ID")
    terminal_id: int | None = Field(None, description="POS terminal of the shift")
    branch_id: int | None = Field(None, description="Branch of the terminal")
    cashier_name: str = Field(description="Cashier name")
    opened_at: str | None = Field(
        None, description="Shift opening timestamp (ISO 8601)"
    )
    status: str = Field(description="Shift status (OPEN or CLOSED)")


class SalesSummary(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    count: int = Field(description="Number of confirmed sales")
    subtotal: DecimalNumber = Field(description="Total before tax and discounts")
    tax: DecimalNumber = Field(description="Total tax amount")
    discount: DecimalNumber = Field(description="Total discount amount")
    total: DecimalNumber = Field(description="Net total (subtotal + tax - discount)")


class RefundSummary(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    count: int = Field(description="Number of completed refunds")
    total: DecimalNumber = Field(description="Total refund amount")


class CashReconciliation(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    opening_balance: DecimalNumber = Field(description="Opening balance")
    cash_sales: DecimalNumber = Field(description="Cash received from sales")
    cash_refunds: DecimalNumber = Field(description="Cash returned in refunds")
    cash_in: DecimalNumber = Field(description="Manual cash-in movements")
    cash_out: DecimalNumber = Field(description="Manual cash-out movements")
    expected_balance: DecimalNumber = Field(description="Expected cash in drawer")
    closing_balance: DecimalNumber | None = Field(
        None, description="Actual closing balance counted"
    )
    discrepancy: DecimalNumber | None = Field(
        None, description="Difference between expected and actual closing balance"
    )


# ---------------------------------------------------------------------------
# X-Report
# ---------------------------------------------------------------------------


class XReportResponse(BaseModel):
    """Mid-shift sales summary (non-closing). Useful for cashier progress checks."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    shift: ShiftInfo = Field(description="Shift information")
    sales_summary: SalesSummary = Field(description="Sales totals for the shift")
    payments_by_method: list[PaymentMethodDetail] = Field(
        description="Breakdown by payment method"
    )
    items_sold: list[ItemSoldDetail] = Field(
        description="Top products sold during the shift"
    )


class XReportQueryParams(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    shift_id: int = Field(..., ge=1, description="Shift ID to generate the report for")


# ---------------------------------------------------------------------------
# Z-Report
# ---------------------------------------------------------------------------


class ZReportResponse(BaseModel):
    """End-of-shift closing report. Includes cash reconciliation and refund data."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    shift: ShiftInfo = Field(description="Shift information")
    sales_summary: SalesSummary = Field(description="Sales totals for the shift")
    payments_by_method: list[PaymentMethodDetail] = Field(
        description="Breakdown by payment method"
    )
    items_sold: list[ItemSoldDetail] = Field(
        description="Products sold during the shift"
    )
    refund_summary: RefundSummary = Field(description="Refund totals for the shift")
    cash_reconciliation: CashReconciliation = Field(
        description="Cash drawer reconciliation"
    )


class ZReportQueryParams(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    shift_id: int = Field(..., ge=1, description="Shift ID to generate the report for")


# ---------------------------------------------------------------------------
# Daily Summary
# ---------------------------------------------------------------------------


class DailySummaryResponse(BaseModel):
    """Daily sales overview across all shifts."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    date: str = Field(description="Report date (YYYY-MM-DD)")
    total_sales: int = Field(description="Number of confirmed sales")
    total_amount: DecimalNumber = Field(description="Total sales amount")
    payments_by_method: list[PaymentMethodDetail] = Field(
        description="Breakdown by payment method"
    )
    top_products: list[ItemSoldDetail] = Field(description="Top selling products")
    refund_summary: RefundSummary = Field(description="Refund totals for the day")


class DailySummaryQueryParams(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    # The default lives in GetDailySummaryQuery: FastAPI ignores default_factory
    # on query models, so an omitted date would fail validation.
    date: dt.date | None = Field(
        None, description="Date for the report (defaults to today)"
    )

    branch_id: int | None = Field(
        None, ge=1, description="Only this branch (one the user may enter)"
    )
    terminal_id: int | None = Field(None, ge=1, description="Only this POS terminal")


# ---------------------------------------------------------------------------
# By Payment Method
# ---------------------------------------------------------------------------


class PaymentMethodSummaryResponse(BaseModel):
    """Sales totals grouped by payment method."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    payment_method: str = Field(description="Payment method name")
    sales_count: int = Field(description="Number of sales using this method")
    total_amount: DecimalNumber = Field(
        description="Total amount collected via this method"
    )


class ByPaymentMethodQueryParams(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    from_date: dt.date | None = Field(None, description="Start date (inclusive)")
    to_date: dt.date | None = Field(None, description="End date (inclusive)")

    branch_id: int | None = Field(
        None, ge=1, description="Only this branch (one the user may enter)"
    )
    terminal_id: int | None = Field(None, ge=1, description="Only this POS terminal")
