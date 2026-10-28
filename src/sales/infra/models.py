from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.infra.database import Base, TenantScoped
from src.shared.infra.precision import MoneyColumn, PercentageColumn


class SaleModel(TenantScoped, Base):
    """Modelo SQLAlchemy para Sales"""

    __tablename__ = "sales"
    __table_args__ = (
        # Composite: the customer is of the sale's tenant
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_sales_customer_tenant",
        ),
        # Composite: where a POS sale is made, in the sale's tenant
        ForeignKeyConstraint(
            ["tenant_id", "branch_id"],
            ["branches.tenant_id", "branches.id"],
            name="fk_sales_branch_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "emission_point_id"],
            ["emission_points.tenant_id", "emission_points.id"],
            name="fk_sales_emission_point_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "terminal_id"],
            ["pos_terminals.tenant_id", "pos_terminals.id"],
            name="fk_sales_terminal_tenant",
        ),
        # The number is a correlative per branch (document_sequences)
        UniqueConstraint(
            "tenant_id", "branch_id", "number", name="uq_sales_tenant_branch_number"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    is_final_consumer: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    shift_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("pos_shifts.id"), nullable=True, index=True
    )
    branch_id: Mapped[int | None] = mapped_column(Integer, index=True)
    emission_point_id: Mapped[int | None] = mapped_column(Integer, index=True)
    terminal_id: Mapped[int | None] = mapped_column(Integer, index=True)
    number: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT")
    sale_date: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    subtotal: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal("0")
    )
    tax: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal("0")
    )
    discount: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal("0")
    )
    discount_type: Mapped[str | None] = mapped_column(String(16))
    discount_value: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal("0")
    )
    total: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal("0")
    )
    payment_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PENDING"
    )
    notes: Mapped[str | None] = mapped_column(String(512))
    created_by: Mapped[str | None] = mapped_column(String(64))
    parked_at: Mapped[datetime | None] = mapped_column(DateTime)
    park_reason: Mapped[str | None] = mapped_column(String(512))
    # PENDING while faclab-invoicing has the invoice, REJECTED after the SRI
    # rejects it; null if it was never sent
    invoice_status: Mapped[str | None] = mapped_column(String(16))
    invoice_id: Mapped[str | None] = mapped_column(String(64))
    invoice_rejection_reason: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.now)

    # Relationships
    items: Mapped[list["SaleItemModel"]] = relationship(
        back_populates="sale", cascade="all, delete-orphan"
    )
    payments: Mapped[list["PaymentModel"]] = relationship(
        back_populates="sale", cascade="all, delete-orphan"
    )


class SaleItemModel(TenantScoped, Base):
    """Modelo SQLAlchemy para Sale Items"""

    __tablename__ = "sale_items"
    __table_args__ = (
        # Composite: the product is of the sale's tenant
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_sale_items_product_tenant",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sale_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    discount: Mapped[Decimal] = mapped_column(
        PercentageColumn, nullable=False, default=Decimal("0")
    )
    tax_code: Mapped[str] = mapped_column(String(16), nullable=False, default="VAT_15")
    tax_amount: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal("0")
    )
    price_override: Mapped[Decimal | None] = mapped_column(MoneyColumn, nullable=True)
    override_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Relationships
    sale: Mapped["SaleModel"] = relationship(back_populates="items")


def _tendered_without_change(context) -> Decimal:
    """A payment written without what was handed over (e.g. by the seed) gave
    no change: it handed over what it applied"""
    params = context.get_current_parameters()
    return params["amount"] + (params.get("change") or Decimal("0"))


class PaymentModel(TenantScoped, Base):
    """Modelo SQLAlchemy para Payments"""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sale_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Applied to the sale; amount_tendered = amount + change
    amount: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    amount_tendered: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=_tendered_without_change
    )
    change: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal("0")
    )
    payment_method: Mapped[str] = mapped_column(String(16), nullable=False)
    payment_date: Mapped[datetime | None] = mapped_column(DateTime)
    reference: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )

    # Relationships
    sale: Mapped["SaleModel"] = relationship(back_populates="payments")
