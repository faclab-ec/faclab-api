from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.quotes.domain.entities import QuoteStatus
from src.shared.domain.tax import TaxCode
from src.shared.infra.validators import DecimalNumber, QuantityNumber, QueryParams


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class QuoteUpdateRequest(_Camel):
    customer_id: int | None = Field(
        None, ge=1, description="Customer it is made for (none: final consumer)"
    )
    valid_until: date = Field(
        description="Last day it is in force: today or later. After it, it can't "
        "be converted until it is renewed"
    )
    notes: str | None = Field(None, max_length=1024, description="Printed on it")


class QuoteRequest(QuoteUpdateRequest):
    branch_id: int = Field(
        ge=1,
        description="Branch that issues it and numbers it; one the user may enter",
    )


class QuoteItemUpdateRequest(_Camel):
    quantity: QuantityNumber | None = Field(
        None, gt=0, description="Quantity in its presentation"
    )
    discount: Decimal | None = Field(
        None, ge=0, le=100, description="Percentage of the line"
    )


class QuoteItemRequest(_Camel):
    product_id: int = Field(ge=1)
    presentation_id: int | None = Field(
        None, ge=1, description="Presentation it is quoted in (none: the base unit)"
    )
    quantity: QuantityNumber = Field(gt=0, description="Quantity in its presentation")
    discount: Decimal = Field(
        Decimal("0"), ge=0, le=100, description="Percentage of the line"
    )


class RenewQuoteRequest(_Camel):
    valid_until: date = Field(description="Its new last day: today or later")


class EmailQuoteRequest(_Camel):
    to: str | None = Field(
        None,
        max_length=254,
        description="Address to send it to (none: the customer's email)",
    )


class QuoteItemResponse(_Camel):
    id: int
    quote_id: int
    product_id: int
    product_name: str | None = None
    product_sku: str | None = None
    presentation_id: int | None = None
    presentation_name: str | None = None
    quantity: QuantityNumber = Field(description="Quantity in its presentation")
    unit_factor: QuantityNumber = Field(
        description="Base units in one of its presentation"
    )
    base_quantity: QuantityNumber = Field(description="Quantity in base units")
    unit_price: DecimalNumber = Field(
        description="Price of one unit of its presentation, from its lists"
    )
    discount: DecimalNumber
    tax_code: TaxCode
    tax_amount: DecimalNumber
    subtotal: DecimalNumber


class QuoteSummaryResponse(_Camel):
    id: int
    number: str | None = Field(
        None, description="Correlative per branch (`COT-001-000012`)"
    )
    branch_id: int
    branch_name: str | None = None
    establishment_code: str | None = None
    customer_id: int | None = Field(None, description="Null: final consumer")
    customer_name: str | None = None
    customer_tax_id: str | None = None
    customer_email: str | None = None
    status: QuoteStatus
    issue_date: date
    valid_until: date
    subtotal: DecimalNumber
    tax: DecimalNumber
    total: DecimalNumber
    notes: str | None = None
    created_by: str | None = None
    sent_at: datetime | None = None
    accepted_at: datetime | None = None
    converted_at: datetime | None = None


class QuoteResponse(QuoteSummaryResponse):
    items: list[QuoteItemResponse]
    sale_id: int | None = Field(None, description="The sale it was converted into")
    sale_number: str | None = None


class PosQuoteItemResponse(QuoteItemResponse):
    list_price: DecimalNumber | None = Field(
        description="What a sale of its customer pays for it today (null: no "
        "price): a quoted price other than this goes as a price override"
    )
    price_list_name: str | None = None
    price_changed: bool = Field(description="The quoted price is not today's")
    available_quantity: QuantityNumber = Field(
        description="Available stock of the product at the terminal's location, "
        "in base units (not reserved: the sale checks it again)"
    )
    enough_stock: bool = Field(
        description="It covers what the quote's lines of the product take"
    )


class PosQuoteResponse(QuoteResponse):
    items: list[PosQuoteItemResponse]  # type: ignore[assignment]
    expired: bool = Field(description="Past its validity: it has to be renewed")


class QuoteQueryParams(QueryParams):
    status: QuoteStatus | None = None
    customer_id: int | None = Field(None, ge=1)
    branch_id: int | None = Field(None, ge=1)
    number: str | None = Field(None, max_length=32, description="Part of the number")


class PosQuoteQueryParams(QueryParams):
    search: str | None = Field(
        None,
        max_length=64,
        description="Part of the number or of the customer's name or tax ID",
    )
