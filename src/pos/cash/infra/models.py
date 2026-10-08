from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base
from src.shared.infra.precision import MoneyColumn


class CashMovementModel(Base):
    __tablename__ = "pos_cash_movements"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    shift_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pos_shifts.id"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(8), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(512))
    performed_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
