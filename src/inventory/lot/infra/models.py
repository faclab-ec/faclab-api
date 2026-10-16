from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.infra.database import Base, TenantScoped


class LotModel(TenantScoped, Base):
    __tablename__ = "lots"
    __table_args__ = (
        UniqueConstraint("product_id", "lot_number", name="uq_lot_product_lot_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    lot_number: Mapped[str] = mapped_column(String(64), nullable=False)
    manufacture_date: Mapped[date | None] = mapped_column(Date)
    expiration_date: Mapped[date | None] = mapped_column(Date)
    initial_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )

    movement_lot_items: Mapped[list["MovementLotItemModel"]] = relationship(
        back_populates="lot", cascade="all, delete-orphan"
    )


class MovementLotItemModel(TenantScoped, Base):
    __tablename__ = "movement_lot_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    movement_id: Mapped[int] = mapped_column(
        ForeignKey("movements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lot_id: Mapped[int] = mapped_column(
        ForeignKey("lots.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    lot: Mapped["LotModel"] = relationship(back_populates="movement_lot_items")
