"""Ejecución de las importaciones confirmadas en el worker (S5.8).

Cada `IMPORT_POLL_INTERVAL_SECONDS` el worker busca como faclab_worker las
importaciones en cola o en curso, la más antigua primero, y corre lotes de
`IMPORT_BATCH_SIZE` filas hasta agotar `IMPORT_TICK_SECONDS` (su salud exige
volver antes de un minuto). Cada lote corre en la empresa de la importación y
a nombre de quien la subió, en su propia transacción: bloquea el trabajo con
SKIP LOCKED (dos workers no toman el mismo), ejecuta sus filas y avanza el
cursor. Si el worker muere a mitad de un lote, ese lote se revierte y el
siguiente tick lo retoma desde el cursor.

Usage (one pass, by hand):
    python -m src.imports.infra.runner
"""

import sys
import time
from dataclasses import dataclass
from uuid import UUID

import structlog
from opentelemetry import trace
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.imports.app.commands.run_import import (
    FailImportCommand,
    FailImportCommandHandler,
    RunImportBatchCommand,
    RunImportBatchCommandHandler,
)
from src.imports.domain.entities import ImportStatus
from src.imports.domain.exceptions import ImportRowFailedError
from src.imports.infra.models import ImportJobModel
from src.shared.domain.tenant import TenantContext, TenantSource
from src.shared.infra.events.scope import create_sync_scope

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

REQUEST_ID_KEY = "http.request.id"


@dataclass(frozen=True)
class PendingImport:
    id: int
    tenant_id: UUID
    user_id: int | None
    user_name: str | None
    branch_id: int | None
    request_id: str | None

    @property
    def tenant(self) -> TenantContext:
        return TenantContext(
            self.tenant_id,
            TenantSource.TASK,
            user_id=self.user_id,
            branch_id=self.branch_id,
            user_name=self.user_name,
        )


def pending_imports(
    session_maker: sessionmaker[Session], limit: int = 10
) -> list[PendingImport]:
    """Las importaciones en cola o en curso de todas las empresas, la que se
    confirmó primero primero"""
    statement = (
        select(
            ImportJobModel.id,
            ImportJobModel.tenant_id,
            ImportJobModel.user_id,
            ImportJobModel.user_name,
            ImportJobModel.branch_id,
            ImportJobModel.request_id,
        )
        .where(
            ImportJobModel.status.in_(
                [ImportStatus.QUEUED.value, ImportStatus.RUNNING.value]
            )
        )
        .order_by(ImportJobModel.confirmed_at, ImportJobModel.id)
        .limit(limit)
    )
    with session_maker() as session:
        return [PendingImport(*row) for row in session.execute(statement).all()]


def run_batch(job: PendingImport, batch_size: int) -> dict:
    """Un lote de la importación, en su empresa. Una fila que falla la detiene
    (en otra transacción: la del lote se revirtió)"""
    with (
        tracer.start_as_current_span(
            "import.batch", attributes={"faclab.import.id": job.id}
        ),
        structlog.contextvars.bound_contextvars(
            **{REQUEST_ID_KEY: job.request_id, "faclab.import.id": job.id}
        ),
    ):
        try:
            with create_sync_scope(tenant=job.tenant) as scope:
                return scope.get(RunImportBatchCommandHandler).handle(
                    RunImportBatchCommand(job_id=job.id, batch_size=batch_size)
                )
        except ImportRowFailedError as exc:
            _fail(job, exc.row_number, exc.reason)
        except Exception as exc:
            logger.exception("import_batch_failed", import_id=job.id)
            _fail(job, None, f"Error inesperado al importar ({type(exc).__name__})")
        return {"locked": False, "status": ImportStatus.FAILED.value, "processed": 0}


def _fail(job: PendingImport, row_number: int | None, message: str) -> None:
    logger.warning("import_failed", import_id=job.id, row=row_number, reason=message)
    with create_sync_scope(tenant=job.tenant) as scope:
        scope.get(FailImportCommandHandler).handle(
            FailImportCommand(job_id=job.id, row_number=row_number, message=message)
        )


def run_imports(
    session_maker: sessionmaker[Session] | None = None,
    batch_size: int | None = None,
    budget_seconds: float | None = None,
) -> int:
    """The worker's task: batches of the pending imports until the budget runs
    out. Returns how many batches it ran"""
    from config import config
    from src.shared.infra.database import worker_session_maker

    session_maker = session_maker or worker_session_maker()
    batch_size = batch_size or config.IMPORT_BATCH_SIZE
    budget = config.IMPORT_TICK_SECONDS if budget_seconds is None else budget_seconds
    deadline = time.monotonic() + budget
    busy: set[int] = set()
    batches = 0
    while time.monotonic() < deadline:
        jobs = [job for job in pending_imports(session_maker) if job.id not in busy]
        if not jobs:
            break
        job = jobs[0]
        result = run_batch(job, batch_size)
        if result["locked"]:
            # Another worker has it: try the next one
            busy.add(job.id)
            continue
        batches += 1
        if result["status"] == ImportStatus.COMPLETED.value:
            logger.info("import_completed", import_id=job.id)
    return batches


def main() -> int:
    from main import app  # noqa: F401  (builds the container)

    run_imports()
    return 0


if __name__ == "__main__":
    sys.exit(main())
