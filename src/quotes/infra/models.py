from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.infra.database import Base, TenantScoped
from src.shared.infra.precision import MoneyColumn, PercentageColumn, QuantityColumn


class QuoteModel(TenantScoped, Base):
    """A quote of a branch (S5.4), numbered when it is created"""

    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_quotes_tenant_number"),
        # Target of the composite foreign key from sales
        UniqueConstraint("tenant_id", "id", name="uq_quotes_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "branch_id"],
            ["branches.tenant_id", "branches.id"],
            name="fk_quotes_branch_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_quotes_customer_tenant",
        ),
        CheckConstraint("valid_until >= issue_date", name="ck_quotes_validity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    number: Mapped[str | None] = mapped_column(String(32))
    customer_id: Mapped[int | None] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="DRAFT", index=True
    )
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal("0")
    )
    tax: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal("0")
    )
    total: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal("0")
    )
    notes: Mapped[str | None] = mapped_column(String(1024))
    created_by: Mapped[str | None] = mapped_column(String(64))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.now)

    items: Mapped[list["QuoteItemModel"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan"
    )


class QuoteItemModel(TenantScoped, Base):
    """A line of a quote, in a presentation of its product"""

    __tablename__ = "quote_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_quote_items_product_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "presentation_id"],
            ["product_presentations.tenant_id", "product_presentations.id"],
            name="fk_quote_items_presentation_tenant",
        ),
        CheckConstraint("quantity > 0", name="ck_quote_items_quantity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    quote_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    presentation_id: Mapped[int | None] = mapped_column(Integer, index=True)
    quantity: Mapped[Decimal] = mapped_column(QuantityColumn, nullable=False)
    unit_factor: Mapped[Decimal] = mapped_column(
        QuantityColumn, nullable=False, default=Decimal(1)
    )
    unit_price: Mapped[Decimal] = mapped_column(MoneyColumn, nullable=False)
    discount: Mapped[Decimal] = mapped_column(
        PercentageColumn, nullable=False, default=Decimal("0")
    )
    tax_code: Mapped[str] = mapped_column(String(16), nullable=False, default="VAT_15")
    tax_amount: Mapped[Decimal] = mapped_column(
        MoneyColumn, nullable=False, default=Decimal("0")
    )

    quote: Mapped["QuoteModel"] = relationship(back_populates="items")
