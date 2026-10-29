from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base, TenantScoped


class AuditLogModel(TenantScoped, Base):
    """An entry of the audit log (S3.5): who did a sensitive operation of the
    tenant, on what, and what changed.

    Rows are only inserted, in the operation's transaction: faclab_app and
    faclab_worker have no UPDATE or DELETE on the table. No foreign key to the
    resource, so the entry outlives it.
    """

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_resource", "resource_type", "resource_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, index=True
    )
    # The token's user; null for a message or a task
    actor_user_id: Mapped[int | None] = mapped_column(index=True)
    # Full name or username at the time
    actor_name: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[int | None] = mapped_column()
    branch_id: Mapped[int | None] = mapped_column(index=True)
    # request, message or task (TenantSource)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(36))
    # Only the relevant fields, as JSON: money as decimal strings
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON)
