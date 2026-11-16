"""Lecturas de la importación masiva (S5.8): plantillas, trabajos, sus filas y
el reporte de errores"""

from dataclasses import dataclass
from typing import Any

from wireup import injectable

from src.imports.app.kinds import TEMPLATES
from src.imports.app.repositories import ImportJobRepository, ImportRowRepository
from src.imports.domain.entities import (
    ImportJob,
    ImportKind,
    ImportRowAction,
    ImportStatus,
)
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError

# Nombre de cada plantilla en los archivos que se descargan
FILE_NAMES = {
    ImportKind.PRODUCTS: "productos",
    ImportKind.PRESENTATIONS: "presentaciones",
    ImportKind.PRICES: "precios",
    ImportKind.CUSTOMERS: "clientes",
    ImportKind.SUPPLIERS: "proveedores",
    ImportKind.STOCK: "saldos-iniciales",
}
# Columnas del reporte de errores antes de las de la plantilla
ERROR_COLUMNS = ("fila", "columna", "codigo", "mensaje")


def job_view(job: ImportJob) -> dict[str, Any]:
    return job.dict()


def _job(jobs: ImportJobRepository, job_id: int) -> ImportJob:
    job = jobs.get_by_id(job_id)
    if job is None:
        raise NotFoundError(f"Import with id {job_id} not found")
    return job


@dataclass
class GetImportTemplatesQuery(Query):
    pass


@injectable(lifetime="scoped")
class GetImportTemplatesQueryHandler(QueryHandler[GetImportTemplatesQuery, list]):
    def _handle(self, query: GetImportTemplatesQuery) -> list[dict[str, Any]]:
        return [
            {
                "kind": kind,
                "file_name": FILE_NAMES[kind],
                "columns": [column.dict() for column in columns],
            }
            for kind, columns in TEMPLATES.items()
        ]


@dataclass
class GetImportTemplateQuery(Query):
    kind: ImportKind


@injectable(lifetime="scoped")
class GetImportTemplateQueryHandler(QueryHandler[GetImportTemplateQuery, dict]):
    """Lo que lleva el archivo de una plantilla: el encabezado y, aparte, qué es
    cada columna"""

    def _handle(self, query: GetImportTemplateQuery) -> dict[str, Any]:
        columns = TEMPLATES[query.kind]
        return {
            "file_name": f"plantilla-{FILE_NAMES[query.kind]}",
            "header": [column.name for column in columns],
            "columns": [column.dict() for column in columns],
        }


@dataclass
class GetImportsQuery(Query):
    kind: ImportKind | None = None
    status: ImportStatus | None = None
    limit: int = 50
    offset: int = 0


@injectable(lifetime="scoped")
class GetImportsQueryHandler(QueryHandler[GetImportsQuery, dict]):
    def __init__(self, jobs: ImportJobRepository):
        self.jobs = jobs

    def _handle(self, query: GetImportsQuery) -> dict[str, Any]:
        page = self.jobs.page(query.kind, query.status, query.limit, query.offset)
        return {**page, "items": [job_view(job) for job in page["items"]]}


@dataclass
class GetImportQuery(Query):
    job_id: int


@injectable(lifetime="scoped")
class GetImportQueryHandler(QueryHandler[GetImportQuery, dict]):
    def __init__(self, jobs: ImportJobRepository):
        self.jobs = jobs

    def _handle(self, query: GetImportQuery) -> dict[str, Any]:
        return job_view(_job(self.jobs, query.job_id))


@dataclass
class GetImportRowsQuery(Query):
    job_id: int
    action: ImportRowAction | None = None
    limit: int = 100
    offset: int = 0


@injectable(lifetime="scoped")
class GetImportRowsQueryHandler(QueryHandler[GetImportRowsQuery, dict]):
    def __init__(self, jobs: ImportJobRepository, rows: ImportRowRepository):
        self.jobs = jobs
        self.rows = rows

    def _handle(self, query: GetImportRowsQuery) -> dict[str, Any]:
        job = _job(self.jobs, query.job_id)
        page = self.rows.page(job.require_id(), query.action, query.limit, query.offset)
        return {**page, "items": [row.dict() for row in page["items"]]}


@dataclass
class GetImportErrorsQuery(Query):
    job_id: int


@injectable(lifetime="scoped")
class GetImportErrorsQueryHandler(QueryHandler[GetImportErrorsQuery, dict]):
    """Una línea por error: la fila, la columna, el código, el mensaje y los
    valores de la fila tal como venían, para corregirla en el archivo"""

    def __init__(self, jobs: ImportJobRepository, rows: ImportRowRepository):
        self.jobs = jobs
        self.rows = rows

    def _handle(self, query: GetImportErrorsQuery) -> dict[str, Any]:
        job = _job(self.jobs, query.job_id)
        columns = [column.name for column in TEMPLATES[job.kind]]
        lines: list[list[Any]] = []
        for row in self.rows.with_errors(job.require_id()):
            values = [row.data.get(name) for name in columns]
            for error in row.errors or []:
                lines.append(
                    [
                        row.row_number,
                        error.get("column"),
                        error.get("code"),
                        error.get("message"),
                        *values,
                    ]
                )
        if job.failed_row is not None or job.failure:
            lines.append([job.failed_row, None, "IMPORT_ROW_FAILED", job.failure])
        return {
            "file_name": f"errores-importacion-{job.require_id()}",
            "header": [*ERROR_COLUMNS, *columns],
            "rows": lines,
        }
