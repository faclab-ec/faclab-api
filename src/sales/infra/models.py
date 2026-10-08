from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.infra.database import Base
from src.shared.infra.precision import MoneyColumn, PercentageColumn


class SaleModel(Base):
    """Modelo SQLAlchemy para Sales"""

    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("customers.id"), nullable=True, index=True
    )
    is_final_consumer: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    shift_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("pos_shifts.id"), nullable=True, index=True
    )
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


class SaleItemModel(Base):
    """Modelo SQLAlchemy para Sale Items"""

    __tablename__ = "sale_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sale_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=False, index=True
    )
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


class PaymentModel(Base):
    """Modelo SQLAlchemy para Payments"""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sale_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(16), nullable=False)
    payment_date: Mapped[datetime | None] = mapped_column(DateTime)
    reference: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )

    # Relationships
    sale: Mapped["SaleModel"] = relationship(back_populates="payments")
