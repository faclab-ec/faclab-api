from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.infra.database import Base, TenantScoped

if TYPE_CHECKING:
    from src.catalog.product.infra.models import ProductModel


class StockModel(TenantScoped, Base):
    __tablename__ = "stocks"
    __table_args__ = (
        # Composite: the product and the location are of the stock's tenant
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_stocks_product_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["locations.tenant_id", "locations.id"],
            name="fk_stocks_location_tenant",
        ),
        UniqueConstraint("product_id", "location_id", name="uq_stock_product_location"),
        # NULLs are distinct in a unique constraint, so the one above lets a
        # product have several stock rows without location. Postgres 14 has no
        # NULLS NOT DISTINCT; a partial unique index covers that case.
        Index(
            "uq_stock_product_without_location",
            "product_id",
            unique=True,
            postgresql_where=text("location_id IS NULL"),
            sqlite_where=text("location_id IS NULL"),
        ),
        # The domain rejects these first (INSUFFICIENT_STOCK); the database
        # is the last barrier for any write that skips it
        CheckConstraint("quantity >= 0", name="ck_stocks_quantity_non_negative"),
        CheckConstraint(
            "reserved_quantity >= 0 AND reserved_quantity <= quantity",
            name="ck_stocks_reserved_quantity_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    location_id: Mapped[int | None] = mapped_column(index=True)
    reserved_quantity: Mapped[int] = mapped_column(default=0)

    product: Mapped["ProductModel"] = relationship(back_populates="stocks")
