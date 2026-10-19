from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base, TenantScoped


class SerialNumberModel(TenantScoped, Base):
    __tablename__ = "serial_numbers"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "serial_number", name="uq_serial_numbers_tenant_serial_number"
        ),
        # Composite: the product, lot and location are of the serial's tenant.
        # SET NULL (column) clears only the reference, never tenant_id
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_serial_numbers_product_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "lot_id"],
            ["lots.tenant_id", "lots.id"],
            name="fk_serial_numbers_lot_tenant",
            ondelete="SET NULL (lot_id)",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["locations.tenant_id", "locations.id"],
            name="fk_serial_numbers_location_tenant",
            ondelete="SET NULL (location_id)",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(nullable=False, index=True)
    serial_number: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="available")
    lot_id: Mapped[int | None]
    location_id: Mapped[int | None]
    purchase_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="SET NULL")
    )
    sale_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
