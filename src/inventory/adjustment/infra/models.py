from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base, TenantScoped


class InventoryAdjustmentModel(TenantScoped, Base):
    __tablename__ = "inventory_adjustments"

    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), index=True)
    reason: Mapped[str]
    status: Mapped[str] = mapped_column(default="draft")
    adjustment_date: Mapped[datetime | None]
    notes: Mapped[str | None]
    adjusted_by: Mapped[str | None]
    created_at: Mapped[datetime | None] = mapped_column(default=datetime.now)


class AdjustmentItemModel(TenantScoped, Base):
    __tablename__ = "adjustment_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    adjustment_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_adjustments.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    expected_quantity: Mapped[int]
    actual_quantity: Mapped[int]
    lot_id: Mapped[int | None] = mapped_column(
        ForeignKey("lots.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None]
