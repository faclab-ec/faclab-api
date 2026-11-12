from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.inventory.movement.domain.constants import MovementType
from src.shared.infra.database import Base, TenantScoped
from src.shared.infra.precision import MoneyColumn, QuantityColumn

if TYPE_CHECKING:
    from src.catalog.product.infra.models import ProductModel


class MovementModel(TenantScoped, Base):
    __tablename__ = "movements"
    __table_args__ = (
        # Composite: the product and the locations are of the movement's tenant
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_movements_product_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["locations.tenant_id", "locations.id"],
            name="fk_movements_location_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_location_id"],
            ["locations.tenant_id", "locations.id"],
            name="fk_movements_source_location_tenant",
        ),
        # The movements of a document (a POS sale is reversed where it took from)
        Index("ix_movements_reference", "reference_type", "reference_id"),
        CheckConstraint("unit_cost >= 0", name="ck_movements_unit_cost_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(index=True)
    quantity: Mapped[Decimal] = mapped_column(QuantityColumn)
    type: Mapped[MovementType]
    location_id: Mapped[int | None] = mapped_column(index=True)
    source_location_id: Mapped[int | None]
    reference_type: Mapped[str | None] = mapped_column(String(64))
    reference_id: Mapped[int | None]
    reason: Mapped[str | None] = mapped_column(String(128))
    date: Mapped[datetime | None] = mapped_column(default=datetime.now, index=True)
    created_at: Mapped[datetime | None] = mapped_column(default=datetime.now)
    # Per base unit (S5.6). The default only serves writes straight through the
    # ORM (the seed, tests): every flow sets the cost it moved at
    unit_cost: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal(0)
    )
    product: Mapped["ProductModel"] = relationship(back_populates="movements")
