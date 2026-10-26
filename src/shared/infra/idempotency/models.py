from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base, TenantScoped

IN_PROGRESS = "in_progress"
COMPLETED = "completed"


class IdempotencyKeyModel(TenantScoped, Base):
    """An `Idempotency-Key` of a tenant and the response its request got (S3.1).

    The request reserves it in its own transaction and stores the response in
    the same one, so a row exists only when the operation committed; a request
    that fails rolls it back and frees the key. The purge removes the rows
    older than `IDEMPOTENCY_KEY_RETENTION_HOURS`.
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_idempotency_keys_tenant_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    # sha256 of the method, the path and the canonical JSON body
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    response_status: Mapped[int | None] = mapped_column()
    # Plain JSON, not JSONB: the replay keeps the order of the keys
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, index=True
    )
