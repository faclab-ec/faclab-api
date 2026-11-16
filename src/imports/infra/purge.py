"""Borra las filas de las importaciones viejas (S5.8), de todas las empresas
(como faclab_worker). El trabajo queda, con sus conteos; sus filas (los valores
del archivo y sus errores) se borran `IMPORT_RETENTION_DAYS` después de que
terminó o, si nunca se confirmó, de que se subió. Una validada que no se
confirmó en ese plazo queda FAILED: ya no tiene filas que ejecutar.

Usage:
    python -m src.imports.infra.purge
"""

import sys
from datetime import datetime, timedelta

import structlog
from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from src.imports.domain.entities import ImportStatus
from src.imports.infra.models import ImportJobModel, ImportRowModel

logger = structlog.get_logger(__name__)

EXPIRED = "La importación venció sin confirmarse"
_FINISHED = [
    ImportStatus.INVALID.value,
    ImportStatus.COMPLETED.value,
    ImportStatus.FAILED.value,
]


def purge_rows(session_maker: sessionmaker[Session], before: datetime) -> int:
    """Borra las filas de los trabajos terminados antes de `before`; devuelve
    cuántas"""
    with session_maker() as session, session.begin():
        session.execute(
            update(ImportJobModel)
            .where(
                ImportJobModel.status == ImportStatus.VALIDATED.value,
                ImportJobModel.created_at < before,
            )
            .values(
                status=ImportStatus.FAILED.value,
                failure=EXPIRED,
                finished_at=datetime.now(),
            )
            .execution_options(synchronize_session=False)
        )
        old = select(ImportJobModel.id).where(
            ImportJobModel.status.in_(_FINISHED),
            or_(
                ImportJobModel.finished_at < before,
                and_(
                    ImportJobModel.finished_at.is_(None),
                    ImportJobModel.created_at < before,
                ),
            ),
        )
        result = session.execute(
            delete(ImportRowModel)
            .where(ImportRowModel.job_id.in_(old))
            .execution_options(synchronize_session=False)
        )
        return result.rowcount


def purge() -> int:
    """The worker's task: purges with the configured retention"""
    from config import config
    from src.shared.infra.database import worker_session_maker

    days = config.IMPORT_RETENTION_DAYS
    deleted = purge_rows(worker_session_maker(), datetime.now() - timedelta(days=days))
    logger.info("import_rows_purged", deleted=deleted, retention_days=days)
    return deleted


def main() -> int:
    purge()
    return 0


if __name__ == "__main__":
    sys.exit(main())
