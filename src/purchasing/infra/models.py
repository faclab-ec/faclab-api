from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.infra.database import Base, TenantScoped
from src.shared.infra.precision import MoneyColumn


class PurchaseOrderModel(TenantScoped, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "order_number", name="uq_purchase_orders_tenant_order_number"
        ),
        # Composite: the supplier is of the order's tenant
        ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.id"],
            name="fk_purchase_orders_supplier_tenant",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(nullable=False, index=True)
    order_number: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    subtotal: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False, default=0)
    tax: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False, default=0)
    total: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    expected_date: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )

    items: Mapped[list["PurchaseOrderItemModel"]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan"
    )
    receipts: Mapped[list["PurchaseReceiptModel"]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan"
    )


class PurchaseOrderItemModel(TenantScoped, Base):
    __tablename__ = "purchase_order_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity_ordered: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_cost: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)

    purchase_order: Mapped["PurchaseOrderModel"] = relationship(back_populates="items")


class PurchaseReceiptModel(TenantScoped, Base):
    __tablename__ = "purchase_receipts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )

    purchase_order: Mapped["PurchaseOrderModel"] = relationship(
        back_populates="receipts"
    )
    items: Mapped[list["PurchaseReceiptItemModel"]] = relationship(
        back_populates="purchase_receipt", cascade="all, delete-orphan"
    )


class PurchaseReceiptItemModel(TenantScoped, Base):
    __tablename__ = "purchase_receipt_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    purchase_receipt_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_receipts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purchase_order_item_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_order_items.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False)
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL")
    )
    lot_number: Mapped[str | None] = mapped_column(String(64))
    serial_numbers: Mapped[list[str] | None] = mapped_column(JSON)

    purchase_receipt: Mapped["PurchaseReceiptModel"] = relationship(
        back_populates="items"
    )
