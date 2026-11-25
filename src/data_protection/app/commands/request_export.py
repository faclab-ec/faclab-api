"""Pedir la exportación de los datos de la empresa (S8.7)"""

from dataclasses import dataclass

from wireup import injectable

from src.data_protection.app.repositories import ExportJobRepository
from src.data_protection.domain.entities import ExportJob
from src.data_protection.domain.exceptions import ExportInProgressError
from src.shared.app.audit import AuditAction, AuditTrail
from src.shared.app.commands import Command, CommandHandler


@dataclass
class RequestDataExportCommand(Command):
    requested_by_id: int | None
    requested_by_name: str | None
    request_id: str | None = None


@injectable(lifetime="scoped")
class RequestDataExportCommandHandler(CommandHandler[RequestDataExportCommand, dict]):
    """La deja en cola para el worker; una a la vez por empresa"""

    def __init__(self, jobs: ExportJobRepository, audit: AuditTrail):
        self.jobs = jobs
        self.audit = audit

    def _handle(self, command: RequestDataExportCommand) -> dict:
        running = self.jobs.in_progress()
        if running is not None:
            raise ExportInProgressError(running.id)
        job = self.jobs.create(
            ExportJob(
                requested_by_id=command.requested_by_id,
                requested_by_name=command.requested_by_name,
                request_id=command.request_id,
            )
        )
        self.audit.record(
            AuditAction.DATA_EXPORT_REQUESTED,
            job.require_id(),
            after={"status": job.status},
        )
        return job.dict()
