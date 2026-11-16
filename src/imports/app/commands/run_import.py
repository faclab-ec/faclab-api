"""Confirmar una importación y ejecutarla por lotes en el worker (S5.8)"""

from dataclasses import dataclass
from datetime import datetime

from wireup import injectable

from src.imports.app.kinds import KindImporters
from src.imports.app.repositories import ImportJobRepository, ImportRowRepository
from src.imports.domain.entities import ImportJob, ImportStatus
from src.imports.domain.exceptions import ImportRowFailedError
from src.shared.app.audit import AuditAction, AuditTrail
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError


def _job(jobs: ImportJobRepository, job_id: int) -> ImportJob:
    job = jobs.get_by_id(job_id)
    if job is None:
        raise NotFoundError(f"Import with id {job_id} not found")
    return job


@dataclass
class ConfirmImportCommand(Command):
    job_id: int
    # The confirming request: the worker's audit entries carry it
    request_id: str | None = None


@injectable(lifetime="scoped")
class ConfirmImportCommandHandler(CommandHandler[ConfirmImportCommand, dict]):
    """La deja en cola para el worker; solo una validada sin errores"""

    def __init__(self, jobs: ImportJobRepository, audit: AuditTrail):
        self.jobs = jobs
        self.audit = audit

    def _handle(self, command: ConfirmImportCommand) -> dict:
        job = _job(self.jobs, command.job_id)
        before = {"status": job.status}
        job.confirm(command.request_id, datetime.now())
        job = self.jobs.update(job)
        self.audit.record(
            AuditAction.IMPORT_CONFIRMED,
            job.require_id(),
            before=before,
            after={
                "status": job.status,
                "kind": job.kind,
                "mode": job.mode,
                "file_name": job.file_name,
                "total_rows": job.total_rows,
                "planned": job.planned,
            },
        )
        return job.dict()


@dataclass
class RunImportBatchCommand(Command):
    job_id: int
    batch_size: int


@injectable(lifetime="scoped")
class RunImportBatchCommandHandler(CommandHandler[RunImportBatchCommand, dict]):
    """Un lote de una importación confirmada, en una transacción: bloquea el
    trabajo (otro worker lo salta), vuelve a planificar las filas siguientes con
    los datos de ahora, las ejecuta con los comandos de su módulo y avanza el
    cursor. Una fila que falla revierte el lote (`ImportRowFailedError`): quien
    lo llama marca la importación fallida en otra transacción."""

    def __init__(
        self,
        jobs: ImportJobRepository,
        rows: ImportRowRepository,
        importers: KindImporters,
    ):
        self.jobs = jobs
        self.rows = rows
        self.importers = importers

    def _handle(self, command: RunImportBatchCommand) -> dict:
        job = self.jobs.lock_for_run(command.job_id)
        if job is None:
            return {"locked": True, "status": None, "processed": 0}
        if not job.in_progress:
            return {"locked": False, "status": job.status.value, "processed": 0}

        now = datetime.now()
        job.start(now)
        batch = self.rows.after(job.require_id(), job.cursor_row, command.batch_size)
        if batch:
            importer = self.importers.of(job.kind)
            plans = importer.plan(batch, job.mode)
            failed = next((plan for plan in plans if plan.errors), None)
            if failed is not None:
                raise ImportRowFailedError(
                    failed.row_number,
                    "; ".join(error.message for error in failed.errors),
                )
            importer.execute(job, plans)
            self.rows.record_results(
                (row.require_id(), plan.action, plan.record_id)
                for row, plan in zip(batch, plans, strict=True)
            )
            job.advance([plan.action for plan in plans], batch[-1].row_number)
        if not batch or job.processed_rows >= job.total_rows:
            job.complete(datetime.now())
        self.jobs.update(job)
        return {"locked": False, "status": job.status.value, "processed": len(batch)}


@dataclass
class FailImportCommand(Command):
    job_id: int
    row_number: int | None
    message: str


@injectable(lifetime="scoped")
class FailImportCommandHandler(CommandHandler[FailImportCommand, dict]):
    """Detiene una importación en la fila que falló; sus lotes anteriores quedan"""

    def __init__(self, jobs: ImportJobRepository):
        self.jobs = jobs

    def _handle(self, command: FailImportCommand) -> dict:
        job = _job(self.jobs, command.job_id)
        if job.status in (ImportStatus.QUEUED, ImportStatus.RUNNING):
            job.fail(command.row_number, command.message, datetime.now())
            job = self.jobs.update(job)
        return job.dict()
