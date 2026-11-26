"""Lecturas de las exportaciones de datos (S8.7)"""

from dataclasses import dataclass

from wireup import injectable

from src.data_protection.app.repositories import ExportJobRepository
from src.data_protection.domain.entities import ExportJob, ExportStatus
from src.data_protection.domain.exceptions import ExportNotReadyError
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError


def _job(jobs: ExportJobRepository, job_id: int) -> ExportJob:
    job = jobs.get_by_id(job_id)
    if job is None:
        raise NotFoundError(f"Data export with id {job_id} not found")
    return job


@dataclass
class GetDataExportsQuery(Query):
    limit: int = 20
    offset: int = 0


@injectable(lifetime="scoped")
class GetDataExportsQueryHandler(QueryHandler[GetDataExportsQuery, dict]):
    def __init__(self, jobs: ExportJobRepository):
        self.jobs = jobs

    def _handle(self, query: GetDataExportsQuery) -> dict:
        page = self.jobs.page(query.limit, query.offset)
        return {**page, "items": [job.dict() for job in page["items"]]}


@dataclass
class GetDataExportQuery(Query):
    job_id: int


@injectable(lifetime="scoped")
class GetDataExportQueryHandler(QueryHandler[GetDataExportQuery, dict]):
    def __init__(self, jobs: ExportJobRepository):
        self.jobs = jobs

    def _handle(self, query: GetDataExportQuery) -> dict:
        return _job(self.jobs, query.job_id).dict()


@injectable(lifetime="scoped")
class GetDataExportFileQueryHandler(QueryHandler[GetDataExportQuery, dict]):
    """La exportación lista para descargar; otra cosa es EXPORT_NOT_READY"""

    def __init__(self, jobs: ExportJobRepository):
        self.jobs = jobs

    def _handle(self, query: GetDataExportQuery) -> dict:
        job = _job(self.jobs, query.job_id)
        if job.status != ExportStatus.READY or not job.file_name:
            raise ExportNotReadyError(job.id, job.status)
        return job.dict()
