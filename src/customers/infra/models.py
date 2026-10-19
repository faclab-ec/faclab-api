from datetime import datetime
from decimal import Decimal

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


class CustomerModel(TenantScoped, Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "tax_id", name="uq_customers_tenant_tax_id"),
        # Target of the composite foreign keys from sales and contacts
        UniqueConstraint("tenant_id", "id", name="uq_customers_tenant_id_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    tax_id: Mapped[str] = mapped_column(String(32), nullable=False)
    tax_type: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    email: Mapped[str | None] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(32))
    address: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str | None] = mapped_column(String(64))
    country: Mapped[str | None] = mapped_column(String(64))
    credit_limit: Mapped[Decimal | None] = mapped_column(MoneyColumn)
    payment_terms: Mapped[int | None] = mapped_column(Integer)  # Days
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )

    contacts: Mapped[list["CustomerContactModel"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )


class CustomerContactModel(TenantScoped, Base):
    __tablename__ = "customer_contacts"
    __table_args__ = (
        # Composite: the customer is of the contact's tenant
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_customer_contacts_customer_tenant",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(32))

    customer: Mapped["CustomerModel"] = relationship(back_populates="contacts")
