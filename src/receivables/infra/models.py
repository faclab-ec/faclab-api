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


class ReceivableModel(TenantScoped, Base):
    """The receivable of a sale on credit (S5.5): one per sale, opened in the
    sale's transaction. Never from a request body: the sale is the one being
    confirmed."""

    __tablename__ = "receivables"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sale_id", name="uq_receivables_tenant_sale_id"),
        # Target of the composite foreign key from its applications
        UniqueConstraint("tenant_id", "id", name="uq_receivables_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_receivables_customer_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "branch_id"],
            ["branches.tenant_id", "branches.id"],
            name="fk_receivables_branch_tenant",
        ),
        CheckConstraint(
            "amount > 0 AND balance >= 0 AND balance <= amount",
            name="ck_receivables_balance",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    sale_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales.id"), nullable=False, index=True
    )
    branch_id: Mapped[int | None] = mapped_column(Integer, index=True)
    amount: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    balance: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    issued_on: Mapped[date] = mapped_column(Date, nullable=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    term_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="OPEN", index=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.now)


class CustomerPaymentModel(TenantScoped, Base):
    """A customer's payment on account (S5.5), at a terminal's open shift or
    outside the cash register, numbered per tenant (`AB-2026-0001`)"""

    __tablename__ = "customer_payments"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "number", name="uq_customer_payments_tenant_number"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_customer_payments_customer_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "branch_id"],
            ["branches.tenant_id", "branches.id"],
            name="fk_customer_payments_branch_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "terminal_id"],
            ["pos_terminals.tenant_id", "pos_terminals.id"],
            name="fk_customer_payments_terminal_tenant",
        ),
        CheckConstraint("amount > 0", name="ck_customer_payments_amount"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    number: Mapped[str | None] = mapped_column(String(32))
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(16), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(String(512))
    paid_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    received_by: Mapped[str | None] = mapped_column(String(64))
    branch_id: Mapped[int | None] = mapped_column(Integer, index=True)
    terminal_id: Mapped[int | None] = mapped_column(Integer, index=True)
    # The terminal's open shift: a cash payment counts in its cash
    shift_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("pos_shifts.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )


class ReceivableApplicationModel(TenantScoped, Base):
    """What a payment on account or a refund took off a receivable's balance"""

    __tablename__ = "receivable_applications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "receivable_id"],
            ["receivables.tenant_id", "receivables.id"],
            name="fk_receivable_applications_receivable_tenant",
        ),
        CheckConstraint("amount > 0", name="ck_receivable_applications_amount"),
        CheckConstraint(
            "(kind = 'PAYMENT' AND customer_payment_id IS NOT NULL "
            "AND refund_id IS NULL) OR "
            "(kind = 'REFUND' AND refund_id IS NOT NULL "
            "AND customer_payment_id IS NULL)",
            name="ck_receivable_applications_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    receivable_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    customer_payment_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("customer_payments.id"), index=True
    )
    refund_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("pos_refunds.id"), index=True
    )
    applied_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
