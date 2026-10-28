from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, Index, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base


class OutboxStatus(StrEnum):
    """`pending` until the relay publishes it; `failed` after the maximum of
    attempts, when it stops holding back its tenant's next messages and waits
    for someone to retry it (`python -m src.background.cli outbox-retry`)."""

    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"


class OutboxMessageModel(Base):
    """Mensaje para Kafka guardado en la misma transacción que lo origina.

    Si la transacción se revierte, el mensaje desaparece con ella; si se
    confirma, el relay lo publica después (y lo reintenta si Kafka no responde).
    """

    __tablename__ = "outbox_messages"
    __table_args__ = (
        # The relay only scans what is still pending, tenant by tenant
        Index(
            "ix_outbox_messages_pending",
            "tenant_id",
            "id",
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    topic: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # Tenant of the transaction that wrote it (also in the faclab-tenant-id
    # header). Infrastructure: the relay reads every tenant's messages
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    # Trace context of the request that wrote the message (W3C traceparent...)
    headers: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=OutboxStatus.PENDING.value
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    # A failed attempt waits until then; null: publish it now
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    # Who put a failed message back in the queue, and when
    retried_at: Mapped[datetime | None] = mapped_column(DateTime)
    retried_by: Mapped[str | None] = mapped_column(String(64))
