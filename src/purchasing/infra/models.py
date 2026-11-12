from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
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
from src.shared.infra.precision import MoneyColumn, QuantityColumn, base_quantity_of


class PurchaseOrderModel(TenantScoped, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "order_number", name="uq_purchase_orders_tenant_order_number"
        ),
        # Target of the composite foreign key from its supplier returns (S5.7)
        UniqueConstraint("tenant_id", "id", name="uq_purchase_orders_tenant_id_id"),
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
    __table_args__ = (
        # Composite: the product is of the order's tenant
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_purchase_order_items_product_tenant",
            ondelete="RESTRICT",
        ),
        # The presentation it is bought in (S5.2); one in use can't be deleted
        ForeignKeyConstraint(
            ["tenant_id", "presentation_id"],
            ["product_presentations.tenant_id", "product_presentations.id"],
            name="fk_purchase_order_items_presentation_tenant",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(nullable=False, index=True)
    quantity_ordered: Mapped[Decimal] = mapped_column(QuantityColumn, nullable=False)
    quantity_received: Mapped[Decimal] = mapped_column(
        QuantityColumn, nullable=False, default=0
    )
    unit_cost: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    presentation_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    unit_factor: Mapped[Decimal] = mapped_column(
        QuantityColumn, nullable=False, default=Decimal(1), server_default="1"
    )
    # The product's VAT when the line was added, and the line's (S5.7)
    tax_code: Mapped[str] = mapped_column(
        String(16), nullable=False, default="VAT_15", server_default="VAT_15"
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal(0), server_default="0"
    )
    # What went back to the supplier, in the line's presentation (S5.7)
    quantity_returned: Mapped[Decimal] = mapped_column(
        QuantityColumn, nullable=False, default=Decimal(0), server_default="0"
    )

    purchase_order: Mapped["PurchaseOrderModel"] = relationship(back_populates="items")


class PurchaseReceiptModel(TenantScoped, Base):
    __tablename__ = "purchase_receipts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime | None] = mapped_column(DateTime)
    # The supplier's invoice for the delivery and what was received, at the
    # order lines' costs with their VAT (S5.7)
    supplier_invoice_number: Mapped[str | None] = mapped_column(String(20))
    subtotal: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal(0), server_default="0"
    )
    tax: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal(0), server_default="0"
    )
    total: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal(0), server_default="0"
    )
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
    __table_args__ = (
        # Composite: the location is of the receipt's tenant. SET NULL (column)
        # clears only the location, never tenant_id
        ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["locations.tenant_id", "locations.id"],
            name="fk_purchase_receipt_items_location_tenant",
            ondelete="SET NULL (location_id)",
        ),
    )

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
    quantity_received: Mapped[Decimal] = mapped_column(QuantityColumn, nullable=False)
    # The order item's factor and what went into stock, in base units (S5.2)
    unit_factor: Mapped[Decimal] = mapped_column(
        QuantityColumn, nullable=False, default=Decimal(1), server_default="1"
    )
    base_quantity: Mapped[Decimal] = mapped_column(
        QuantityColumn, nullable=False, default=base_quantity_of("quantity_received")
    )
    location_id: Mapped[int | None]
    lot_number: Mapped[str | None] = mapped_column(String(64))
    serial_numbers: Mapped[list[str] | None] = mapped_column(JSON)

    purchase_receipt: Mapped["PurchaseReceiptModel"] = relationship(
        back_populates="items"
    )


class SupplierReturnModel(TenantScoped, Base):
    """Goods of a purchase order going back to the supplier (S5.7), numbered
    per tenant (`DP-2026-0001`)"""

    __tablename__ = "supplier_returns"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "number", name="uq_supplier_returns_tenant_number"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.id"],
            name="fk_supplier_returns_supplier_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "purchase_order_id"],
            ["purchase_orders.tenant_id", "purchase_orders.id"],
            name="fk_supplier_returns_purchase_order_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "credited_amount >= 0 AND credited_amount <= total",
            name="ck_supplier_returns_credited_amount",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    number: Mapped[str | None] = mapped_column(String(32))
    supplier_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    purchase_order_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)
    supplier_credit_note_number: Mapped[str | None] = mapped_column(String(20))
    subtotal: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False, default=0)
    tax: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False, default=0)
    total: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False, default=0)
    credited_amount: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=0
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    confirmed_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )


class SupplierReturnItemModel(TenantScoped, Base):
    """A line of a supplier return: part of what an order line received, with
    the line's cost, VAT and presentation"""

    __tablename__ = "supplier_return_items"
    __table_args__ = (
        # Where it leaves from, a location a request names
        ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["locations.tenant_id", "locations.id"],
            name="fk_supplier_return_items_location_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint("quantity > 0", name="ck_supplier_return_items_quantity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    supplier_return_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_returns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purchase_order_item_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_order_items.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    presentation_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_presentations.id", ondelete="RESTRICT"), index=True
    )
    quantity: Mapped[Decimal] = mapped_column(QuantityColumn, nullable=False)
    unit_factor: Mapped[Decimal] = mapped_column(
        QuantityColumn, nullable=False, default=Decimal(1)
    )
    base_quantity: Mapped[Decimal] = mapped_column(
        QuantityColumn, nullable=False, default=base_quantity_of("quantity")
    )
    unit_cost: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    tax_code: Mapped[str] = mapped_column(String(16), nullable=False, default="VAT_15")
    tax_amount: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal(0)
    )
    location_id: Mapped[int | None] = mapped_column(Integer, index=True)
