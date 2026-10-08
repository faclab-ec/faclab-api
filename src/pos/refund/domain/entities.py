from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from src.pos.refund.domain.exceptions import InvalidRefundStatusError
from src.sales.domain.entities import PaymentMethod
from src.shared.domain.entities import Entity
from src.shared.domain.tax import TaxCode


class RefundStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


@dataclass
class Refund(Entity):
    original_sale_id: int
    shift_id: int | None = None
    refund_date: datetime | None = None
    subtotal: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    reason: str | None = None
    status: RefundStatus = RefundStatus.PENDING
    refunded_by: str | None = None
    id: int | None = None
    created_at: datetime | None = None

    def complete(self) -> None:
        if self.status != RefundStatus.PENDING:
            raise InvalidRefundStatusError(self.status, "complete")
        self.status = RefundStatus.COMPLETED
        self.refund_date = datetime.now()

    def cancel(self) -> None:
        if self.status != RefundStatus.PENDING:
            raise InvalidRefundStatusError(self.status, "cancel")
        self.status = RefundStatus.CANCELLED


@dataclass
class RefundItem(Entity):
    refund_id: int
    original_sale_item_id: int
    product_id: int
    quantity: int
    unit_price: Decimal
    discount: Decimal = Decimal("0")
    tax_code: TaxCode = TaxCode.VAT_15
    tax_amount: Decimal = Decimal("0")
    id: int | None = None

    @property
    def subtotal(self) -> Decimal:
        base = self.unit_price * self.quantity
        discount_amount = base * (self.discount / Decimal("100"))
        return base - discount_amount


@dataclass
class RefundPayment(Entity):
    refund_id: int
    amount: Decimal
    payment_method: PaymentMethod
    reference: str | None = None
    id: int | None = None
    created_at: datetime | None = None

    def __post_init__(self):
        if self.amount <= Decimal("0"):
            raise ValueError(f"Payment amount must be positive, got {self.amount}")
