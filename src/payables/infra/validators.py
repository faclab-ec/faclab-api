from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.payables.domain.entities import PayableApplicationKind, PayableStatus
from src.sales.domain.entities import PaymentMethod
from src.shared.infra.validators import DecimalNumber, QueryParams


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PayableQueryParams(QueryParams):
    supplier_id: int | None = Field(None, ge=1)
    status: PayableStatus | None = None
    purchase_order_id: int | None = Field(None, ge=1)
    overdue: bool | None = Field(
        None, description="true: open and past their due date; false: the rest"
    )


class PayableResponse(_Camel):
    id: int
    supplier_id: int
    supplier_name: str | None = None
    supplier_tax_id: str | None = None
    purchase_order_id: int
    order_number: str | None = Field(None, description="`PO-2026-0001`")
    purchase_receipt_id: int
    supplier_invoice_number: str | None = Field(
        None, description="The supplier's invoice for the delivery"
    )
    amount: DecimalNumber = Field(description="What was received, with VAT")
    balance: DecimalNumber = Field(description="What is still owed")
    issued_on: date = Field(description="The day it was received")
    due_on: date
    term_days: int = Field(description="The supplier's payment terms, in days")
    status: PayableStatus
    days_overdue: int = Field(
        description="Days past its due date while open; 0 if not yet due"
    )
    created_at: datetime | None = None


class PayableApplicationResponse(_Camel):
    id: int
    kind: PayableApplicationKind
    amount: DecimalNumber
    applied_at: datetime
    supplier_payment_id: int | None = None
    supplier_return_id: int | None = None
    document_number: str | None = Field(
        None, description="The payment's number (`PP-2026-0001`) or the return's"
    )
    payment_method: PaymentMethod | None = None


class PayableDetailResponse(PayableResponse):
    applications: list[PayableApplicationResponse]


class SupplierPaymentApplicationInput(_Camel):
    payable_id: int = Field(ge=1)
    amount: Decimal = Field(gt=0)


class SupplierPaymentRequest(_Camel):
    supplier_id: int = Field(ge=1)
    amount: Decimal = Field(gt=0, description="What is paid, to the cent")
    payment_method: PaymentMethod = Field(description="Any method but CREDIT")
    reference: str | None = Field(
        None, max_length=128, description="Transfer or check number"
    )
    notes: str | None = Field(None, max_length=512)
    applications: list[SupplierPaymentApplicationInput] | None = Field(
        None,
        description="What it pays of each open payable, adding up to the amount; "
        "without them it goes to the oldest due first (FIFO)",
    )


class SupplierPaymentApplicationResponse(_Camel):
    payable_id: int
    purchase_order_id: int
    supplier_invoice_number: str | None = None
    amount: DecimalNumber
    balance: DecimalNumber = Field(description="The payable's balance now")


class SupplierPaymentSummaryResponse(_Camel):
    id: int
    number: str | None = Field(None, description="`PP-2026-0001`")
    supplier_id: int
    supplier_name: str | None = None
    amount: DecimalNumber
    payment_method: PaymentMethod
    reference: str | None = None
    notes: str | None = None
    paid_at: datetime
    paid_by: str | None = None


class SupplierPaymentResponse(SupplierPaymentSummaryResponse):
    applications: list[SupplierPaymentApplicationResponse]


class SupplierPaymentQueryParams(QueryParams):
    supplier_id: int | None = Field(None, ge=1)


class SupplierReturnCreditResponse(_Camel):
    """A confirmed supplier return and what it credited"""

    id: int
    number: str | None = Field(None, description="`DP-2026-0001`")
    purchase_order_id: int
    order_number: str | None = None
    supplier_credit_note_number: str | None = None
    total: DecimalNumber
    credited_amount: DecimalNumber = Field(
        description="What it took off the accounts payable"
    )
    refund_due: DecimalNumber = Field(description="What the supplier has to refund")
    confirmed_at: datetime | None = None


class SupplierAccountResponse(_Camel):
    supplier_id: int
    supplier_name: str
    supplier_tax_id: str
    payment_terms: int | None = Field(None, description="Days")
    outstanding: DecimalNumber = Field(description="What is owed to the supplier")
    overdue: DecimalNumber = Field(description="What is owed past due")
    payables: list[PayableResponse] = Field(description="Its open payables")
    payments: list[SupplierPaymentSummaryResponse] = Field(
        description="Its last payments, the last one first"
    )
    returns: list[SupplierReturnCreditResponse] = Field(
        description="Its last confirmed returns, the last one first"
    )
