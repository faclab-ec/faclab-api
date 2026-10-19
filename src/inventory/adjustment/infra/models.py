from datetime import datetime

from sqlalchemy import ForeignKey, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base, TenantScoped


class InventoryAdjustmentModel(TenantScoped, Base):
    __tablename__ = "inventory_adjustments"
    __table_args__ = (
        # Composite: the warehouse is of the adjustment's tenant
        ForeignKeyConstraint(
            ["tenant_id", "warehouse_id"],
            ["warehouses.tenant_id", "warehouses.id"],
            name="fk_inventory_adjustments_warehouse_tenant",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(index=True)
    reason: Mapped[str]
    status: Mapped[str] = mapped_column(default="draft")
    adjustment_date: Mapped[datetime | None]
    notes: Mapped[str | None]
    adjusted_by: Mapped[str | None]
    created_at: Mapped[datetime | None] = mapped_column(default=datetime.now)


class AdjustmentItemModel(TenantScoped, Base):
    __tablename__ = "adjustment_items"
    __table_args__ = (
        # Composite: the product, location and lot are of the item's tenant.
        # SET NULL (column) clears only the lot, never tenant_id
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_adjustment_items_product_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["locations.tenant_id", "locations.id"],
            name="fk_adjustment_items_location_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "lot_id"],
            ["lots.tenant_id", "lots.id"],
            name="fk_adjustment_items_lot_tenant",
            ondelete="SET NULL (lot_id)",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    adjustment_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_adjustments.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int]
    location_id: Mapped[int]
    expected_quantity: Mapped[int]
    actual_quantity: Mapped[int]
    lot_id: Mapped[int | None] = mapped_column(nullable=True)
    notes: Mapped[str | None]
