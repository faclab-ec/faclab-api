from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.infra.database import Base
from src.shared.infra.precision import MoneyColumn

if TYPE_CHECKING:
    from src.inventory.movement.infra.models import MovementModel
    from src.inventory.stock.infra.models import StockModel


class CategoryModel(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(128))

    products: Mapped[list["ProductModel"]] = relationship(back_populates="category")


class ProductModel(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    barcode: Mapped[str | None] = mapped_column(String(64), unique=True)
    purchase_price: Mapped[Decimal | None] = mapped_column(MoneyColumn)
    sale_price: Mapped[Decimal | None] = mapped_column(MoneyColumn)
    tax_code: Mapped[str] = mapped_column(String(16), nullable=False, default="VAT_15")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_service: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    min_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_stock: Mapped[int | None] = mapped_column(Integer)
    reorder_point: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )

    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id"), nullable=True, index=True
    )
    unit_of_measure_id: Mapped[int | None] = mapped_column(
        ForeignKey("units_of_measure.id"), nullable=True
    )
    category: Mapped["CategoryModel | None"] = relationship(back_populates="products")
    # Inventory history must survive product deletion: let the database FKs
    # reject deleting a product that has movements or stock (409).
    movements: Mapped[list["MovementModel"]] = relationship(
        back_populates="product", passive_deletes="all"
    )
    stocks: Mapped[list["StockModel"]] = relationship(
        back_populates="product", passive_deletes="all"
    )
