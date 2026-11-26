"""Runs the data exports in the worker (S8.7).

Every `DATA_EXPORT_POLL_INTERVAL_SECONDS` the worker looks, as faclab_worker, for
the oldest QUEUED export of any company (or a RUNNING one whose worker died,
`DATA_EXPORT_STALE_MINUTES`), claims it with SKIP LOCKED and writes its ZIP in a
thread of its own: a large company takes minutes and the worker's health needs
every task back within one. The ZIP is read in one REPEATABLE READ transaction,
so its tables agree with each other.

Usage (one pass, by hand):
    python -m src.data_protection.infra.runner
"""

import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import structlog
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from src.data_protection.domain.entities import ExportStatus
from src.data_protection.infra.exporter import write_export
from src.data_protection.infra.models import ExportJobModel

logger = structlog.get_logger(__name__)

_running: threading.Thread | None = None


@dataclass(frozen=True)
class ClaimedExport:
    id: int
    tenant_id: UUID
    request_id: str | None


def export_file(tenant_id: UUID, file_name: str) -> Path:
    """Where a company's ZIP lives; `file_name` is ours, never a request's"""
    from config import config

    return Path(config.DATA_EXPORT_DIR) / str(tenant_id) / file_name


def claim(
    session_maker: sessionmaker[Session], now: datetime, stale_minutes: int
) -> ClaimedExport | None:
    """The oldest export waiting, now RUNNING; None if nothing waits or another
    worker took it"""
    stale = now - timedelta(minutes=stale_minutes)
    with session_maker() as session, session.begin():
        row = session.execute(
            select(
                ExportJobModel.id, ExportJobModel.tenant_id, ExportJobModel.request_id
            )
            .where(
                or_(
                    ExportJobModel.status == ExportStatus.QUEUED.value,
                    (ExportJobModel.status == ExportStatus.RUNNING.value)
                    & (ExportJobModel.started_at < stale),
                )
            )
            .order_by(ExportJobModel.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if row is None:
            return None
        session.execute(
            update(ExportJobModel)
            .where(ExportJobModel.id == row.id)
            .values(status=ExportStatus.RUNNING.value, started_at=now)
            .execution_options(synchronize_session=False)
        )
        return ClaimedExport(row.id, row.tenant_id, row.request_id)


def run_export(
    session_maker: sessionmaker[Session],
    job: ClaimedExport,
    retention_days: int,
    now: datetime | None = None,
) -> bool:
    """Writes the job's ZIP and records the result; False if it failed"""
    now = now or datetime.now()
    file_name = f"export-{job.id}-{now:%Y%m%d%H%M%S}.zip"
    path = export_file(job.tenant_id, file_name)
    with structlog.contextvars.bound_contextvars(
        **{"http.request.id": job.request_id, "faclab.export.id": job.id}
    ):
        try:
            with session_maker() as session:
                # The first call on the session: it sets the isolation level of
                # the transaction it begins. Read only, nothing to commit
                options = (
                    {"isolation_level": "REPEATABLE READ"}
                    if session.get_bind().dialect.name == "postgresql"
                    else {}
                )
                session.connection(execution_options=options)
                counts = write_export(session, job.tenant_id, path)
                session.rollback()
            values = {
                "status": ExportStatus.READY.value,
                "file_name": file_name,
                "file_size": path.stat().st_size,
                "tables": counts,
                "failure": None,
                "finished_at": datetime.now(),
                "expires_at": now + timedelta(days=retention_days),
            }
            logger.info("data_export_ready", rows=sum(counts.values()))
            ok = True
        except Exception as exc:
            # The type only: the message of a database error can quote data
            logger.error("data_export_failed", error_type=type(exc).__name__)
            path.unlink(missing_ok=True)
            values = {
                "status": ExportStatus.FAILED.value,
                "failure": f"Export failed ({type(exc).__name__})",
                "finished_at": datetime.now(),
            }
            ok = False
    with session_maker() as session, session.begin():
        session.execute(
            update(ExportJobModel)
            .where(ExportJobModel.id == job.id)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
    return ok


def run_exports(
    session_maker: sessionmaker[Session] | None = None, wait: bool = False
) -> int:
    """The worker's task: starts the oldest waiting export unless one is
    already running here. Returns how many it started. `wait` joins the thread
    (tests, the manual pass)"""
    global _running
    from config import config
    from src.shared.infra.database import worker_session_maker

    if _running is not None and _running.is_alive():
        return 0
    session_maker = session_maker or worker_session_maker()
    job = claim(session_maker, datetime.now(), config.DATA_EXPORT_STALE_MINUTES)
    if job is None:
        return 0
    thread = threading.Thread(
        target=run_export,
        args=(session_maker, job, config.DATA_EXPORT_RETENTION_DAYS),
        name=f"data-export-{job.id}",
        daemon=True,
    )
    _running = thread
    thread.start()
    if wait:
        thread.join()
    return 1


def main() -> int:
    from main import app  # noqa: F401  (builds the container)

    run_exports(wait=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
