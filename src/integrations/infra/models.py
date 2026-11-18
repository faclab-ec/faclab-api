from datetime import date, datetime
from uuid import UUID

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base, TenantScoped


class IntegrationClientModel(TenantScoped, Base):
    """An integration client of the tenant (S6.2). Its scopes, branches and
    networks are JSON lists: the branches are checked when they are set, and a
    deleted branch left in the list only narrows the client further."""

    __tablename__ = "integration_clients"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "public_id", name="uq_integration_clients_tenant_public_id"
        ),
        # Target of the composite foreign key from the sales it creates (S6.3)
        UniqueConstraint("tenant_id", "id", name="uq_integration_clients_tenant_id_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # The OAuth client_id (fl_live_… / fl_test_…), unique on the platform
    # through integration_client_directory
    public_id: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    # Null: every branch / any address
    branch_ids: Mapped[list[int] | None] = mapped_column(JSON)
    allowed_ips: Mapped[list[str] | None] = mapped_column(JSON)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


class ClientSecretModel(TenantScoped, Base):
    """A secret of a client: only its SHA-256 and the first characters"""

    __tablename__ = "integration_client_secrets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("integration_clients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)


class IntegrationUsageModel(TenantScoped, Base):
    """A client's usage in a day: counters, not a row per request, and only
    the last source address"""

    __tablename__ = "integration_client_usage"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "client_id",
            "day",
            name="uq_integration_client_usage_tenant_client_day",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("integration_clients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    token_requests: Mapped[int] = mapped_column(nullable=False, default=0)
    token_failures: Mapped[int] = mapped_column(nullable=False, default=0)
    requests: Mapped[int] = mapped_column(nullable=False, default=0)
    errors: Mapped[int] = mapped_column(nullable=False, default=0)
    last_ip: Mapped[str | None] = mapped_column(String(45))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)


class IntegrationClientDirectoryModel(Base):
    """client_id → tenant, without row-level security: the token endpoint
    learns the tenant from the client_id before it can see the client, which
    is the tenant's (like auth_sessions, it is filtered by hand)"""

    __tablename__ = "integration_client_directory"

    public_id: Mapped[str] = mapped_column(String(24), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now)
