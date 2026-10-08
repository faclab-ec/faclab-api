from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.infra.database import Base

if TYPE_CHECKING:
    from src.catalog.product.infra.models import ProductModel


class StockModel(Base):
    __tablename__ = "stocks"
    __table_args__ = (
        UniqueConstraint("product_id", "location_id", name="uq_stock_product_location"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    reserved_quantity: Mapped[int] = mapped_column(default=0)

    product: Mapped["ProductModel"] = relationship(back_populates="stocks")
