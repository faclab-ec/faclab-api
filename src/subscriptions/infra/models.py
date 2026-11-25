from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base, TenantScoped


class PlanModel(Base):
    """A platform table: no tenant, no row-level security. Every tenant reads
    its plan; only the platform (faclab_worker) writes them"""

    __tablename__ = "plans"
    __table_args__ = (
        # One default plan, the one new tenants get
        Index(
            "uq_plans_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
            sqlite_where=text("is_default"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # NULL: no limit
    max_branches: Mapped[int | None] = mapped_column(Integer)
    max_terminals: Mapped[int | None] = mapped_column(Integer)
    max_users: Mapped[int | None] = mapped_column(Integer)
    max_integration_clients: Mapped[int | None] = mapped_column(Integer)
    max_webhook_endpoints: Mapped[int | None] = mapped_column(Integer)
    max_monthly_documents: Mapped[int | None] = mapped_column(Integer)
    public_api: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )


class SubscriptionModel(TenantScoped, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        # One per tenant
        UniqueConstraint("tenant_id", name="uq_subscriptions_tenant"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # A platform row: a single-column key
    plan_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime)
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime)
    status_changed_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )


class DocumentUsageModel(TenantScoped, Base):
    """The electronic documents the SRI authorized to a tenant, per month"""

    __tablename__ = "document_usage"
    __table_args__ = (
        UniqueConstraint("tenant_id", "period", name="uq_document_usage_tenant_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # The first day of the month, in Ecuador
    period: Mapped[date] = mapped_column(Date, nullable=False)
    invoices: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    credit_notes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
