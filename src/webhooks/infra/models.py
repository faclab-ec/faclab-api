"""The webhooks' tables (S6.4). All of them are the tenant's, with row-level
security; the worker reads and sends them across tenants as faclab_worker."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base, TenantScoped


class WebhookEndpointModel(TenantScoped, Base):
    __tablename__ = "webhook_endpoints"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_webhook_endpoints_tenant_id_id"),
        # The integration client it belongs to: one of the tenant
        ForeignKeyConstraint(
            ["tenant_id", "integration_client_id"],
            ["integration_clients.tenant_id", "integration_clients.id"],
            name="fk_webhook_endpoints_integration_client_tenant",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    event_types: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    disabled_reason: Mapped[str | None] = mapped_column(String(32))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime)
    integration_client_id: Mapped[int | None] = mapped_column(Integer, index=True)
    exclude_own_changes: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # Encrypted with SECRET_ENCRYPTION_KEYS (Fernet)
    secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    secret_hint: Mapped[str] = mapped_column(String(16), nullable=False)
    previous_secret_ciphertext: Mapped[str | None] = mapped_column(Text)
    previous_secret_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)
    failing_since: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


class WebhookMessageModel(TenantScoped, Base):
    """An event as it is sent: the whole body, the same in every attempt and to
    every endpoint"""

    __tablename__ = "webhook_messages"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "public_id", name="uq_webhook_messages_tenant_public_id"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # The webhook-id: msg_…
    public_id: Mapped[str] = mapped_column(String(40), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # The integration client whose request caused it (like audit_log's actor)
    origin_integration_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, index=True
    )


class WebhookDeliveryModel(TenantScoped, Base):
    """A message on its way to one endpoint"""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        # What the worker sends: the pending ones by due time
        Index(
            "ix_webhook_deliveries_pending",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
        # An endpoint's history, newest first
        Index("ix_webhook_deliveries_endpoint_created", "endpoint_id", "created_at"),
        # The endpoints with a delivery on its way, which wait for it
        Index(
            "ix_webhook_deliveries_locked",
            "locked_until",
            postgresql_where=text("locked_until IS NOT NULL"),
            sqlite_where=text("locked_until IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("webhook_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    endpoint_id: Mapped[int] = mapped_column(
        ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    # While it is being sent: the lease of the worker that claimed it
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    response_status: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(String(500))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)
    retried_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )


class WebhookStockChangeModel(TenantScoped, Base):
    """A stock row that changed, waiting to be told as `stock.changed`: the
    worker groups them by product and branch every 30 s and deletes them. Only
    inserts, without a unique key, so concurrent sales never wait for it"""

    __tablename__ = "webhook_stock_changes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(Integer, nullable=False)
    location_id: Mapped[int] = mapped_column(Integer, nullable=False)
    origin_integration_id: Mapped[int | None] = mapped_column(Integer)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
