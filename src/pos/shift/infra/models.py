from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base, TenantScoped
from src.shared.infra.precision import MoneyColumn


class ShiftModel(TenantScoped, Base):
    """Modelo SQLAlchemy para Shifts"""

    __tablename__ = "pos_shifts"
    __table_args__ = (
        # Composite: the terminal and the branch are of the shift's tenant
        ForeignKeyConstraint(
            ["tenant_id", "terminal_id"],
            ["pos_terminals.tenant_id", "pos_terminals.id"],
            name="fk_pos_shifts_terminal_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "branch_id"],
            ["branches.tenant_id", "branches.id"],
            name="fk_pos_shifts_branch_tenant",
        ),
        # At most one open shift per terminal, also between concurrent requests
        Index(
            "uq_pos_shifts_tenant_terminal_open",
            "tenant_id",
            "terminal_id",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
            sqlite_where=text("status = 'OPEN'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cashier_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # Null only in shifts from before S2.6
    terminal_id: Mapped[int | None] = mapped_column(Integer, index=True)
    branch_id: Mapped[int | None] = mapped_column(Integer, index=True)
    opened_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_pos_shifts_opened_by_user")
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    opening_balance: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal("0")
    )
    closing_balance: Mapped[Decimal | None] = mapped_column(MoneyColumn)
    expected_balance: Mapped[Decimal | None] = mapped_column(MoneyColumn)
    discrepancy: Mapped[Decimal | None] = mapped_column(MoneyColumn)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    notes: Mapped[str | None] = mapped_column(String(512))
    closed_by: Mapped[str | None] = mapped_column(String(128))


class ShiftClosingModel(TenantScoped, Base):
    """The Z closing of a shift (S5.9): written once, in the transaction that
    closes it. faclab_app and faclab_worker can't update nor delete it"""

    __tablename__ = "pos_shift_closings"
    __table_args__ = (
        # One closing per shift
        UniqueConstraint(
            "tenant_id", "shift_id", name="uq_pos_shift_closings_tenant_shift_id"
        ),
        # A correlative per terminal
        UniqueConstraint(
            "tenant_id",
            "terminal_id",
            "sequence",
            name="uq_pos_shift_closings_tenant_terminal_sequence",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "terminal_id"],
            ["pos_terminals.tenant_id", "pos_terminals.id"],
            name="fk_pos_shift_closings_terminal_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "branch_id"],
            ["branches.tenant_id", "branches.id"],
            name="fk_pos_shift_closings_branch_tenant",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    shift_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pos_shifts.id"), nullable=False, index=True
    )
    # Null only for a shift from before S2.6
    terminal_id: Mapped[int | None] = mapped_column(Integer, index=True)
    branch_id: Mapped[int | None] = mapped_column(Integer, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    number: Mapped[str] = mapped_column(String(64), nullable=False)
    cashier_name: Mapped[str] = mapped_column(String(128), nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime)
    closed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    closed_by: Mapped[str | None] = mapped_column(String(128))
    closed_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_pos_shift_closings_closed_by_user")
    )
    opening_balance: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    sales_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sales_subtotal: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    sales_tax: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    sales_discount: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    sales_total: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    refunds_count: Mapped[int] = mapped_column(Integer, nullable=False)
    refunds_total: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    cash_sales: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    cash_refunds: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    customer_payments: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    cash_in: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    cash_out: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    justification_threshold: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(String(512))
    # The products sold, as they were at the closing: quantities and totals as
    # decimal text
    items_sold: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )


class ShiftClosingLineModel(TenantScoped, Base):
    """The count of one payment method in a Z closing (S5.9)"""

    __tablename__ = "pos_shift_closing_lines"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "closing_id",
            "payment_method",
            name="uq_pos_shift_closing_lines_tenant_closing_method",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    closing_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pos_shift_closings.id"), nullable=False, index=True
    )
    payment_method: Mapped[str] = mapped_column(String(16), nullable=False)
    payments_count: Mapped[int] = mapped_column(Integer, nullable=False)
    payments_total: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    customer_payments_count: Mapped[int] = mapped_column(Integer, nullable=False)
    customer_payments_total: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False
    )
    refunds_total: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    # Null for CREDIT, which is not counted
    expected: Mapped[Decimal | None] = mapped_column(MoneyColumn)
    counted: Mapped[Decimal | None] = mapped_column(MoneyColumn)
    difference: Mapped[Decimal | None] = mapped_column(MoneyColumn)
    justification: Mapped[str | None] = mapped_column(String(512))
