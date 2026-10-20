from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.infra.database import Base, TenantScoped
from src.shared.infra.precision import MoneyColumn, PercentageColumn


class RefundModel(TenantScoped, Base):
    __tablename__ = "pos_refunds"
    __table_args__ = (
        # Composite: the branch and the terminal are of the refund's tenant
        ForeignKeyConstraint(
            ["tenant_id", "branch_id"],
            ["branches.tenant_id", "branches.id"],
            name="fk_pos_refunds_branch_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "terminal_id"],
            ["pos_terminals.tenant_id", "pos_terminals.id"],
            name="fk_pos_refunds_terminal_tenant",
        ),
        # The number is a correlative per branch (document_sequences)
        UniqueConstraint(
            "tenant_id",
            "branch_id",
            "number",
            name="uq_pos_refunds_tenant_branch_number",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    original_sale_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales.id"), nullable=False, index=True
    )
    shift_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("pos_shifts.id"), nullable=True, index=True
    )
    branch_id: Mapped[int | None] = mapped_column(Integer, index=True)
    terminal_id: Mapped[int | None] = mapped_column(Integer, index=True)
    number: Mapped[str | None] = mapped_column(String(32))
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


class RefundItemModel(TenantScoped, Base):
    __tablename__ = "pos_refund_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    refund_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("pos_refunds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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


class RefundPaymentModel(TenantScoped, Base):
    __tablename__ = "pos_refund_payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    refund_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("pos_refunds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(16), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )

    refund: Mapped["RefundModel"] = relationship(back_populates="payments")
