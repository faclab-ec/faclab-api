from datetime import datetime

from sqlalchemy import ForeignKey, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base, TenantScoped


class StockTransferModel(TenantScoped, Base):
    __tablename__ = "stock_transfers"
    __table_args__ = (
        # Composite: both locations are of the transfer's tenant
        ForeignKeyConstraint(
            ["tenant_id", "source_location_id"],
            ["locations.tenant_id", "locations.id"],
            name="fk_stock_transfers_source_location_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "destination_location_id"],
            ["locations.tenant_id", "locations.id"],
            name="fk_stock_transfers_destination_location_tenant",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_location_id: Mapped[int] = mapped_column(index=True)
    destination_location_id: Mapped[int]
    status: Mapped[str] = mapped_column(default="draft")
    transfer_date: Mapped[datetime | None]
    requested_by: Mapped[str | None]
    notes: Mapped[str | None]
    created_at: Mapped[datetime | None] = mapped_column(default=datetime.now)


class StockTransferItemModel(TenantScoped, Base):
    __tablename__ = "stock_transfer_items"
    __table_args__ = (
        # Composite: the product and lot are of the item's tenant. SET NULL
        # (column) clears only the lot, never tenant_id
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_stock_transfer_items_product_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "lot_id"],
            ["lots.tenant_id", "lots.id"],
            name="fk_stock_transfer_items_lot_tenant",
            ondelete="SET NULL (lot_id)",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_id: Mapped[int] = mapped_column(
        ForeignKey("stock_transfers.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int]
    quantity: Mapped[int]
    lot_id: Mapped[int | None] = mapped_column(nullable=True)
    notes: Mapped[str | None]
