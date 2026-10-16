from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.infra.database import Base, TenantScoped
from src.shared.infra.precision import MoneyColumn


class SupplierModel(TenantScoped, Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "tax_id", name="uq_suppliers_tenant_tax_id"),
        # Target of the composite foreign key from purchase orders
        UniqueConstraint("tenant_id", "id", name="uq_suppliers_tenant_id_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    tax_id: Mapped[str] = mapped_column(String(32), nullable=False)
    tax_type: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    email: Mapped[str | None] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(32))
    address: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(64))
    country: Mapped[str | None] = mapped_column(String(64))
    payment_terms: Mapped[int | None] = mapped_column(Integer)  # Credit days
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )

    contacts: Mapped[list["SupplierContactModel"]] = relationship(
        back_populates="supplier", cascade="all, delete-orphan"
    )
    products: Mapped[list["SupplierProductModel"]] = relationship(
        back_populates="supplier", cascade="all, delete-orphan"
    )


class SupplierContactModel(TenantScoped, Base):
    __tablename__ = "supplier_contacts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(32))

    supplier: Mapped["SupplierModel"] = relationship(back_populates="contacts")


class SupplierProductModel(TenantScoped, Base):
    __tablename__ = "supplier_products"
    __table_args__ = (UniqueConstraint("supplier_id", "product_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purchase_price: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    supplier_sku: Mapped[str | None] = mapped_column(String(64))
    min_order_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    supplier: Mapped["SupplierModel"] = relationship(back_populates="products")
