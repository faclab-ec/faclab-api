from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base, TenantScoped


class UnitOfMeasureModel(TenantScoped, Base):
    __tablename__ = "units_of_measure"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "symbol", name="uq_units_of_measure_tenant_symbol"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
