from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base, TenantScoped
from src.shared.infra.precision import MoneyColumn, QuantityColumn


class PriceListModel(TenantScoped, Base):
    """A price list of the company (S5.3): retail, wholesale, by volume. The
    general one (`is_default`, one per company) only holds quantity tiers: its
    base price is the product's"""

    __tablename__ = "price_lists"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_price_lists_tenant_name"),
        # Target of the composite foreign keys from items, customers and branches
        UniqueConstraint("tenant_id", "id", name="uq_price_lists_tenant_id_id"),
        # One general list per company
        Index(
            "uq_price_lists_tenant_default",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_default"),
            sqlite_where=text("is_default"),
        ),
        CheckConstraint(
            "valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to",
            name="ck_price_lists_validity",
        ),
        CheckConstraint(
            "NOT is_default OR (is_active AND valid_from IS NULL AND valid_to IS NULL)",
            name="ck_price_lists_default",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )


class PriceListItemModel(TenantScoped, Base):
    """The price of a presentation of a product in a list, from a quantity in
    that presentation: 0 is the list's base price, more is a volume tier"""

    __tablename__ = "price_list_items"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "price_list_id",
            "presentation_id",
            "min_quantity",
            name="uq_price_list_items_tenant_list_presentation_min",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "price_list_id"],
            ["price_lists.tenant_id", "price_lists.id"],
            name="fk_price_list_items_price_list_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_price_list_items_product_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "presentation_id"],
            ["product_presentations.tenant_id", "product_presentations.id"],
            name="fk_price_list_items_presentation_tenant",
            ondelete="CASCADE",
        ),
        CheckConstraint("price >= 0", name="ck_price_list_items_price"),
        CheckConstraint("min_quantity >= 0", name="ck_price_list_items_min_quantity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    price_list_id: Mapped[int] = mapped_column(nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(nullable=False, index=True)
    presentation_id: Mapped[int] = mapped_column(nullable=False, index=True)
    min_quantity: Mapped[Decimal] = mapped_column(
        QuantityColumn, nullable=False, default=0
    )
    price: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
