from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infra.database import Base, TenantScoped


class ImportJobModel(TenantScoped, Base):
    """A bulk import (S5.8): the file a user uploaded, what its rows would do
    and how far the worker got. Never from a request body: the upload builds it"""

    __tablename__ = "import_jobs"
    __table_args__ = (
        # The worker picks the oldest confirmed one
        Index("ix_import_jobs_status_confirmed_at", "status", "confirmed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Rows per action ({"CREATE": 950, "UPDATE": 50, ...}): planned when the
    # file was validated, done by the worker
    planned: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    done: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    processed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # The last row the worker executed: the next batch starts after it
    cursor_row: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Who uploaded it (the worker runs it in their name) and from which branch
    user_id: Mapped[int | None] = mapped_column(Integer)
    user_name: Mapped[str | None] = mapped_column(String(64))
    branch_id: Mapped[int | None] = mapped_column(Integer)
    # The request that confirmed it, carried by the worker's audit entries
    request_id: Mapped[str | None] = mapped_column(String(36))
    failed_row: Mapped[int | None] = mapped_column(Integer)
    failure: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class ImportRowModel(TenantScoped, Base):
    """A row of an import's file, as it came (text by template header), with
    what it does and, once done, the record it wrote"""

    __tablename__ = "import_job_rows"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "job_id",
            "row_number",
            name="uq_import_job_rows_tenant_job_row",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("import_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Its line in the sheet: the header is line 1
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    errors: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    record_id: Mapped[int | None] = mapped_column(Integer)
