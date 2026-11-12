from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base, TenantScoped
from src.shared.infra.precision import MoneyColumn


class PayableModel(TenantScoped, Base):
    """What is owed for a purchase receipt (S5.7): one per receipt with a total,
    opened in the receipt's transaction. Never from a request body."""

    __tablename__ = "payables"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "purchase_receipt_id",
            name="uq_payables_tenant_purchase_receipt_id",
        ),
        # Target of the composite foreign key from its applications
        UniqueConstraint("tenant_id", "id", name="uq_payables_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.id"],
            name="fk_payables_supplier_tenant",
        ),
        CheckConstraint(
            "amount > 0 AND balance >= 0 AND balance <= amount",
            name="ck_payables_balance",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    purchase_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_orders.id"), nullable=False, index=True
    )
    purchase_receipt_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_receipts.id"), nullable=False, index=True
    )
    supplier_invoice_number: Mapped[str | None] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    balance: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    issued_on: Mapped[date] = mapped_column(Date, nullable=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    term_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="OPEN", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.now)


class SupplierPaymentModel(TenantScoped, Base):
    """A payment to a supplier (S5.7), numbered per tenant (`PP-2026-0001`)"""

    __tablename__ = "supplier_payments"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "number", name="uq_supplier_payments_tenant_number"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.id"],
            name="fk_supplier_payments_supplier_tenant",
        ),
        CheckConstraint("amount > 0", name="ck_supplier_payments_amount"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    number: Mapped[str | None] = mapped_column(String(32))
    supplier_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(16), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(String(512))
    paid_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    paid_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )


class PayableApplicationModel(TenantScoped, Base):
    """What a payment or a supplier return took off a payable's balance"""

    __tablename__ = "payable_applications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "payable_id"],
            ["payables.tenant_id", "payables.id"],
            name="fk_payable_applications_payable_tenant",
        ),
        CheckConstraint("amount > 0", name="ck_payable_applications_amount"),
        CheckConstraint(
            "(kind = 'PAYMENT' AND supplier_payment_id IS NOT NULL "
            "AND supplier_return_id IS NULL) OR "
            "(kind = 'RETURN' AND supplier_return_id IS NOT NULL "
            "AND supplier_payment_id IS NULL)",
            name="ck_payable_applications_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    payable_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    supplier_payment_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("supplier_payments.id"), index=True
    )
    supplier_return_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("supplier_returns.id"), index=True
    )
    applied_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
