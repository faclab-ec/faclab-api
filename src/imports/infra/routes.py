from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from wireup import Injected

from config import config
from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import require_permission
from src.imports.app.commands.create_import import (
    CreateImportCommand,
    CreateImportCommandHandler,
)
from src.imports.app.commands.run_import import (
    ConfirmImportCommand,
    ConfirmImportCommandHandler,
)
from src.imports.app.queries.imports import (
    GetImportErrorsQuery,
    GetImportErrorsQueryHandler,
    GetImportQuery,
    GetImportQueryHandler,
    GetImportRowsQuery,
    GetImportRowsQueryHandler,
    GetImportsQuery,
    GetImportsQueryHandler,
    GetImportTemplateQuery,
    GetImportTemplateQueryHandler,
    GetImportTemplatesQuery,
    GetImportTemplatesQueryHandler,
)
from src.imports.domain.entities import ImportKind, ImportMode
from src.imports.domain.exceptions import ImportFileInvalidError
from src.imports.infra.sheets import (
    CSV_MEDIA_TYPE,
    XLSX_MEDIA_TYPE,
    read_table,
    write_csv,
    write_xlsx,
)
from src.imports.infra.validators import (
    ImportJobResponse,
    ImportQueryParams,
    ImportRowQueryParams,
    ImportRowResponse,
    ImportTemplateResponse,
    SheetFormat,
)
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import (
    RESPONSES_COMMAND,
    RESPONSES_LIST,
    RESPONSES_QUERY,
    DataResponse,
    ListResponse,
    Meta,
    PaginatedDataResponse,
)

_WRITE = [Depends(require_permission(Permission.IMPORT_WRITE))]

_FILE_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "content": {XLSX_MEDIA_TYPE: {}, "text/csv": {}},
        "description": "The sheet, as XLSX (default) or CSV",
    },
    **RESPONSES_QUERY,
}
_FORMAT = Query(SheetFormat.XLSX, alias="format", description="xlsx (default) or csv")


def _sheet(
    document: dict[str, Any],
    sheet_format: SheetFormat,
    title: str,
    notes: list[list[Any]] | None = None,
) -> Response:
    if sheet_format == SheetFormat.CSV:
        content = write_csv(document["header"], document.get("rows", []))
        media_type = CSV_MEDIA_TYPE
    else:
        content = write_xlsx(document["header"], document.get("rows", []), title, notes)
        media_type = XLSX_MEDIA_TYPE
    file_name = f"{document['file_name']}.{sheet_format.value}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


def _instructions(columns: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        ["Columna", "Obligatoria", "Descripción", "Ejemplo"],
        *(
            [
                column["name"],
                "Siempre"
                if column["key"] and column["required"]
                else "Para crear"
                if column["required"]
                else "No",
                column["description"],
                column["example"],
            ]
            for column in columns
        ),
    ]


class ImportRouter:
    """Importación masiva de datos iniciales (S5.8) en /api/admin/imports"""

    def __init__(self):
        self.router = APIRouter()
        route = self.router
        route.get(
            "/templates",
            response_model=ListResponse[ImportTemplateResponse],
            summary="Get the import templates and their columns",
            responses=RESPONSES_LIST,
            dependencies=_WRITE,
        )(self.templates)
        route.get(
            "/templates/{kind}",
            summary="Download an import template",
            response_class=Response,
            responses=_FILE_RESPONSES,
            dependencies=_WRITE,
        )(self.template)
        route.post(
            "",
            response_model=DataResponse[ImportJobResponse],
            status_code=status.HTTP_201_CREATED,
            summary="Upload a file and validate it, without importing it",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.create)
        route.get(
            "",
            response_model=PaginatedDataResponse[ImportJobResponse],
            summary="Get the imports, the last one first",
            responses=RESPONSES_LIST,
            dependencies=_WRITE,
        )(self.get_all)
        route.get(
            "/{id}",
            response_model=DataResponse[ImportJobResponse],
            summary="Get an import and its progress",
            responses=RESPONSES_QUERY,
            dependencies=_WRITE,
        )(self.get_by_id)
        route.get(
            "/{id}/rows",
            response_model=PaginatedDataResponse[ImportRowResponse],
            summary="Get the rows of an import, with their errors",
            responses=RESPONSES_QUERY,
            dependencies=_WRITE,
        )(self.rows)
        route.get(
            "/{id}/errors",
            summary="Download the errors of an import, one per line",
            response_class=Response,
            responses=_FILE_RESPONSES,
            dependencies=_WRITE,
        )(self.errors)
        route.post(
            "/{id}/confirm",
            response_model=DataResponse[ImportJobResponse],
            summary="Confirm a validated import: the worker runs it",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.confirm)

    def templates(
        self,
        handler: Injected[GetImportTemplatesQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> ListResponse[ImportTemplateResponse]:
        """Every template in the order they are loaded: products, presentations,
        prices, customers, suppliers and opening stock. A key column identifies
        the record; a required one is needed to create it."""
        result = handler.handle(GetImportTemplatesQuery())
        return ListResponse(
            data=[ImportTemplateResponse.model_validate(t) for t in result], meta=meta
        )

    def template(
        self,
        kind: ImportKind,
        handler: Injected[GetImportTemplateQueryHandler],
        sheet_format: SheetFormat = _FORMAT,
    ) -> Response:
        """The template's header. As XLSX its cells are text (Excel keeps the
        leading zeros) and a second sheet explains each column."""
        result = handler.handle(GetImportTemplateQuery(kind=kind))
        return _sheet(
            result,
            sheet_format,
            result["file_name"].removeprefix("plantilla-"),
            _instructions(result["columns"]),
        )

    def create(
        self,
        handler: Injected[CreateImportCommandHandler],
        kind: ImportKind = Form(description="Which template the file follows"),
        mode: ImportMode = Form(
            ImportMode.SKIP,
            description="SKIP: rows of records that exist are skipped; UPDATE: "
            "their filled cells update them",
        ),
        file: UploadFile = File(description="CSV (comma or semicolon) or XLSX"),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ImportJobResponse]:
        """Reads the file, checks every row against the tenant's data and keeps
        what each one would do. Nothing is imported: the import is VALIDATED
        (confirm it) or INVALID (see its rows with `action=ERROR` or download
        the errors). A file that can't be read answers IMPORT_FILE_INVALID."""
        size = file.size or 0
        if size > config.IMPORT_MAX_FILE_BYTES:
            raise ImportFileInvalidError(
                f"El archivo pasa de {config.IMPORT_MAX_FILE_BYTES // (1024 * 1024)} MB: "
                "divídalo",
                detail=f"size={size}",
            )
        file_name = file.filename or "archivo"
        table = read_table(file.file, file_name)
        result = handler.handle(
            CreateImportCommand(
                kind=kind,
                mode=mode,
                file_name=file_name,
                file_size=size,
                header=table.header,
                rows=table.rows,
                max_rows=config.IMPORT_MAX_ROWS,
            )
        )
        return DataResponse(data=ImportJobResponse.model_validate(result), meta=meta)

    def get_all(
        self,
        handler: Injected[GetImportsQueryHandler],
        query_params: ImportQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[ImportJobResponse]:
        result = handler.handle(
            GetImportsQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[ImportJobResponse.model_validate(job) for job in result["items"]],
            meta=meta.with_pagination(
                total=result["total"], limit=result["limit"], offset=result["offset"]
            ),
        )

    def get_by_id(
        self,
        id: int,
        handler: Injected[GetImportQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ImportJobResponse]:
        """While QUEUED or RUNNING, `processedRows` of `totalRows` is its
        progress."""
        result = handler.handle(GetImportQuery(job_id=id))
        return DataResponse(data=ImportJobResponse.model_validate(result), meta=meta)

    def rows(
        self,
        id: int,
        handler: Injected[GetImportRowsQueryHandler],
        query_params: ImportRowQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[ImportRowResponse]:
        result = handler.handle(
            GetImportRowsQuery(job_id=id, **query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[ImportRowResponse.model_validate(row) for row in result["items"]],
            meta=meta.with_pagination(
                total=result["total"], limit=result["limit"], offset=result["offset"]
            ),
        )

    def errors(
        self,
        id: int,
        handler: Injected[GetImportErrorsQueryHandler],
        sheet_format: SheetFormat = _FORMAT,
    ) -> Response:
        """One line per error: row, column, code, message and the row's cells as
        they came. The row that stopped a FAILED import goes last."""
        result = handler.handle(GetImportErrorsQuery(job_id=id))
        return _sheet(result, sheet_format, "errores")

    def confirm(
        self,
        id: int,
        handler: Injected[ConfirmImportCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ImportJobResponse]:
        """Queues a VALIDATED import (IMPORT_NOT_CONFIRMABLE otherwise): the
        worker runs it in batches with each module's commands, in the name of
        who uploaded it. Audited (`import.confirmed`)."""
        result = handler.handle(
            ConfirmImportCommand(job_id=id, request_id=meta.request_id)
        )
        return DataResponse(data=ImportJobResponse.model_validate(result), meta=meta)
