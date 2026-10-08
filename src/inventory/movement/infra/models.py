from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.inventory.movement.domain.constants import MovementType
from src.shared.infra.database import Base

if TYPE_CHECKING:
    from src.catalog.product.infra.models import ProductModel


class MovementModel(Base):
    __tablename__ = "movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int]
    type: Mapped[MovementType]
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    source_location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    reference_type: Mapped[str | None] = mapped_column(String(64))
    reference_id: Mapped[int | None]
    reason: Mapped[str | None] = mapped_column(String(128))
    date: Mapped[datetime | None] = mapped_column(default=datetime.now)
    created_at: Mapped[datetime | None] = mapped_column(default=datetime.now)
    product: Mapped["ProductModel"] = relationship(back_populates="movements")
