from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.inventory.location.domain.entities import LocationType
from src.shared.infra.database import Base, TenantScoped


class LocationModel(TenantScoped, Base):
    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("warehouse_id", "code", name="uq_location_warehouse_code"),
        # Target of the composite foreign keys from stock, movements and transfers
        UniqueConstraint("tenant_id", "id", name="uq_locations_tenant_id_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    type: Mapped[LocationType] = mapped_column(default=LocationType.STORAGE)
    is_active: Mapped[bool] = mapped_column(default=True)
    capacity: Mapped[int | None]
