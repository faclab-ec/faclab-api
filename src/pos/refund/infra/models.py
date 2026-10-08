from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.infra.database import Base
from src.shared.infra.precision import MoneyColumn, PercentageColumn


class RefundModel(Base):
    __tablename__ = "pos_refunds"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    original_sale_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales.id"), nullable=False
    )
    shift_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("pos_shifts.id"), nullable=True
    )
    refund_date: Mapped[datetime | None] = mapped_column(DateTime)
    subtotal: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal("0")
    )
    tax: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal("0")
    )
    total: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal("0")
    )
    reason: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    refunded_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )

    items: Mapped[list["RefundItemModel"]] = relationship(
        back_populates="refund", cascade="all, delete-orphan"
    )
    payments: Mapped[list["RefundPaymentModel"]] = relationship(
        back_populates="refund", cascade="all, delete-orphan"
    )


class RefundItemModel(Base):
    __tablename__ = "pos_refund_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    refund_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pos_refunds.id", ondelete="CASCADE"), nullable=False
    )
    original_sale_item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sale_items.id"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    discount: Mapped[Decimal] = mapped_column(
        PercentageColumn, nullable=False, default=Decimal("0")
    )
    tax_code: Mapped[str] = mapped_column(String(16), nullable=False, default="VAT_15")
    tax_amount: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal("0")
    )

    refund: Mapped["RefundModel"] = relationship(back_populates="items")


class RefundPaymentModel(Base):
    __tablename__ = "pos_refund_payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    refund_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pos_refunds.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(16), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )

    refund: Mapped["RefundModel"] = relationship(back_populates="payments")
