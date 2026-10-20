from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
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
