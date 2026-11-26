from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base, TenantScoped


class ExportJobModel(TenantScoped, Base):
    """The export of a company's data (S8.7): who asked, how far the worker got
    and the ZIP it left. Never from a request body."""

    __tablename__ = "export_jobs"
    __table_args__ = (
        # The worker picks the oldest queued one
        Index("ix_export_jobs_status_id", "status", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_by_id: Mapped[int | None] = mapped_column(Integer)
    requested_by_name: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(36))
    # The ZIP's name inside DATA_EXPORT_DIR/<tenant id>/
    file_name: Mapped[str | None] = mapped_column(String(128))
    file_size: Mapped[int | None] = mapped_column(Integer)
    tables: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    failure: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
