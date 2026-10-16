from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base, TenantScoped
from src.shared.infra.precision import MoneyColumn


class ShiftModel(TenantScoped, Base):
    """Modelo SQLAlchemy para Shifts"""

    __tablename__ = "pos_shifts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cashier_name: Mapped[str] = mapped_column(String(128), nullable=False)
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
