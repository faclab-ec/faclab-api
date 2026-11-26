"""Deletes the data exports' ZIPs once they expire (S8.7), every company, as
faclab_worker. The job stays (who asked and when) as EXPIRED; its file goes
`DATA_EXPORT_RETENTION_DAYS` after it was ready. Idempotent.

Usage:
    python -m src.data_protection.infra.purge
"""

import sys
from datetime import datetime

import structlog
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from src.data_protection.domain.entities import ExportStatus
from src.data_protection.infra.models import ExportJobModel
from src.data_protection.infra.runner import export_file

logger = structlog.get_logger(__name__)


def purge_files(session_maker: sessionmaker[Session], now: datetime) -> int:
    """Expires the ready exports past `expires_at`; returns how many"""
    with session_maker() as session, session.begin():
        expired = session.execute(
            select(
                ExportJobModel.id, ExportJobModel.tenant_id, ExportJobModel.file_name
            ).where(
                ExportJobModel.status == ExportStatus.READY.value,
                ExportJobModel.expires_at < now,
            )
        ).all()
        for job in expired:
            if job.file_name:
                export_file(job.tenant_id, job.file_name).unlink(missing_ok=True)
        if expired:
            session.execute(
                update(ExportJobModel)
                .where(ExportJobModel.id.in_([job.id for job in expired]))
                .values(status=ExportStatus.EXPIRED.value)
                .execution_options(synchronize_session=False)
            )
        return len(expired)


def purge() -> int:
    """The worker's task"""
    from src.shared.infra.database import worker_session_maker

    expired = purge_files(worker_session_maker(), datetime.now())
    logger.info("data_export_files_purged", expired=expired)
    return expired


def main() -> int:
    purge()
    return 0


if __name__ == "__main__":
    sys.exit(main())
