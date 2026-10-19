from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.infra.database import Base, TenantScoped
from src.shared.infra.precision import MoneyColumn

if TYPE_CHECKING:
    from src.inventory.movement.infra.models import MovementModel
    from src.inventory.stock.infra.models import StockModel


class CategoryModel(TenantScoped, Base):
    __tablename__ = "categories"
    __table_args__ = (
        # Target of the composite foreign key from products
        UniqueConstraint("tenant_id", "id", name="uq_categories_tenant_id_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(128))

    # Only category_id: deleting a category leaves its products without one,
    # and the ORM must not null the products' tenant_id of the composite key
    products: Mapped[list["ProductModel"]] = relationship(
        back_populates="category", foreign_keys="ProductModel.category_id"
    )


class ProductModel(TenantScoped, Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku", name="uq_products_tenant_sku"),
        UniqueConstraint("tenant_id", "barcode", name="uq_products_tenant_barcode"),
        # Target of the composite foreign keys from items, stock and movements
        UniqueConstraint("tenant_id", "id", name="uq_products_tenant_id_id"),
        # Composite: the category and the unit are of the product's tenant
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["categories.tenant_id", "categories.id"],
            name="fk_products_category_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "unit_of_measure_id"],
            ["units_of_measure.tenant_id", "units_of_measure.id"],
            name="fk_products_unit_of_measure_tenant",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    barcode: Mapped[str | None] = mapped_column(String(64))
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

    category_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    unit_of_measure_id: Mapped[int | None] = mapped_column(nullable=True)
    category: Mapped["CategoryModel | None"] = relationship(
        back_populates="products", foreign_keys=[category_id]
    )
    # Inventory history must survive product deletion: let the database FKs
    # reject deleting a product that has movements or stock (409).
    movements: Mapped[list["MovementModel"]] = relationship(
        back_populates="product", passive_deletes="all"
    )
    stocks: Mapped[list["StockModel"]] = relationship(
        back_populates="product", passive_deletes="all"
    )
