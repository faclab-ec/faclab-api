from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.receivables.domain.entities import ReceivableApplicationKind, ReceivableStatus
from src.sales.domain.entities import PaymentMethod
from src.shared.infra.validators import DecimalNumber, QueryParams


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ReceivableQueryParams(QueryParams):
    customer_id: int | None = Field(None, ge=1)
    status: ReceivableStatus | None = None
    overdue: bool | None = Field(
        None, description="true: open and past their due date; false: the rest"
    )
    branch_id: int | None = Field(None, ge=1)


class ReceivableResponse(_Camel):
    id: int
    customer_id: int
    customer_name: str | None = None
    customer_tax_id: str | None = None
    sale_id: int
    sale_number: str | None = Field(None, description="`V-001-000123`")
    branch_id: int | None = None
    amount: DecimalNumber = Field(description="What the sale left on credit")
    balance: DecimalNumber = Field(description="What is still owed")
    issued_on: date
    due_on: date
    term_days: int = Field(description="The customer's payment terms, in days")
    status: ReceivableStatus
    cancelled_at: datetime | None = None
    days_overdue: int = Field(
        description="Days past its due date while open; 0 if not yet due"
    )
    created_at: datetime | None = None


class ReceivableApplicationResponse(_Camel):
    id: int
    kind: ReceivableApplicationKind
    amount: DecimalNumber
    applied_at: datetime
    customer_payment_id: int | None = None
    refund_id: int | None = None
    document_number: str | None = Field(
        None, description="The payment's number (`AB-2026-0001`) or the refund's"
    )
    payment_method: PaymentMethod | None = None


class ReceivableDetailResponse(ReceivableResponse):
    applications: list[ReceivableApplicationResponse]


class AgingTotalsResponse(BaseModel):
    """Balances by days past their due date"""

    model_config = ConfigDict(populate_by_name=True)

    not_due: DecimalNumber = Field(alias="notDue", description="Not yet due")
    days_1_30: DecimalNumber = Field(alias="days1To30")
    days_31_60: DecimalNumber = Field(alias="days31To60")
    days_61_90: DecimalNumber = Field(alias="days61To90")
    over_90: DecimalNumber = Field(alias="over90")
    total: DecimalNumber


class AgingRowResponse(AgingTotalsResponse):
    customer_id: int = Field(alias="customerId")
    customer_name: str = Field(alias="customerName")
    customer_tax_id: str = Field(alias="customerTaxId")
    receivables: int = Field(description="Open receivables")


class AgingResponse(_Camel):
    as_of: date
    customers: list[AgingRowResponse]
    totals: AgingTotalsResponse


class CustomerAccountResponse(_Camel):
    customer_id: int
    customer_name: str
    customer_tax_id: str
    credit_limit: DecimalNumber | None = None
    payment_terms: int | None = Field(None, description="Days")
    has_credit: bool = Field(
        description="Active with a credit limit: it may buy on credit"
    )
    outstanding: DecimalNumber = Field(description="What it owes")
    overdue: DecimalNumber = Field(description="What it owes past due")
    available: DecimalNumber = Field(description="Credit limit minus what it owes")
    receivables: list[ReceivableResponse] = Field(description="Its open receivables")


class StatementQueryParams(_Camel):
    from_date: date | None = Field(None, description="First day (whole day)")
    to_date: date | None = Field(None, description="Last day (whole day)")


class StatementLineResponse(_Camel):
    type: Literal["SALE", "PAYMENT", "REFUND", "CANCELLATION"] = Field(
        description="A sale on credit (charge), a payment on account, a refund "
        "credited to the account or a cancelled sale (credits)"
    )
    id: int
    date: datetime
    document_number: str | None = None
    charge: DecimalNumber
    credit: DecimalNumber
    balance: DecimalNumber = Field(description="What the customer owes after it")
    receivable_id: int | None = None
    sale_id: int | None = None
    customer_payment_id: int | None = None
    refund_id: int | None = None
    due_on: date | None = None
    payment_method: PaymentMethod | None = None


class StatementResponse(_Camel):
    customer_id: int
    customer_name: str
    customer_tax_id: str
    from_date: date | None = None
    to_date: date | None = None
    opening_balance: DecimalNumber
    lines: list[StatementLineResponse]
    closing_balance: DecimalNumber


class PaymentApplicationInput(_Camel):
    receivable_id: int = Field(ge=1)
    amount: Decimal = Field(gt=0)


class CustomerPaymentRequest(_Camel):
    customer_id: int = Field(ge=1)
    amount: Decimal = Field(gt=0, description="What it pays, to the cent")
    payment_method: PaymentMethod = Field(description="Any method but CREDIT")
    reference: str | None = Field(None, max_length=128)
    notes: str | None = Field(None, max_length=512)
    applications: list[PaymentApplicationInput] | None = Field(
        None,
        description="What it pays of each open receivable, adding up to the amount; "
        "without them it goes to the oldest due first (FIFO)",
    )


class CustomerPaymentApplicationResponse(_Camel):
    receivable_id: int
    sale_id: int
    sale_number: str | None = None
    amount: DecimalNumber
    balance: DecimalNumber = Field(description="The receivable's balance now")


class CustomerPaymentSummaryResponse(_Camel):
    id: int
    number: str | None = Field(None, description="`AB-2026-0001`")
    customer_id: int
    customer_name: str | None = None
    amount: DecimalNumber
    payment_method: PaymentMethod
    reference: str | None = None
    notes: str | None = None
    paid_at: datetime
    received_by: str | None = None
    branch_id: int | None = None
    terminal_id: int | None = None
    shift_id: int | None = Field(
        None, description="The shift whose cash took it, at the POS"
    )


class CustomerPaymentResponse(CustomerPaymentSummaryResponse):
    applications: list[CustomerPaymentApplicationResponse]


class CustomerPaymentQueryParams(QueryParams):
    customer_id: int | None = Field(None, ge=1)
