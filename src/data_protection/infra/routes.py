from fastapi import APIRouter, Depends, status
from fastapi.responses import FileResponse
from wireup import Injected

from src.auth.domain.entities import AuthenticatedUser
from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import get_current_user, require_permission
from src.data_protection.app.commands.request_export import (
    RequestDataExportCommand,
    RequestDataExportCommandHandler,
)
from src.data_protection.app.queries.exports import (
    GetDataExportFileQueryHandler,
    GetDataExportQuery,
    GetDataExportQueryHandler,
    GetDataExportsQuery,
    GetDataExportsQueryHandler,
)
from src.data_protection.infra.runner import export_file
from src.data_protection.infra.validators import ExportQueryParams, ExportResponse
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tenant import require_tenant
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import (
    RESPONSES_COMMAND,
    RESPONSES_LIST,
    RESPONSES_QUERY,
    DataResponse,
    Meta,
    PaginatedDataResponse,
)

_EXPORT = [Depends(require_permission(Permission.DATA_EXPORT))]


class DataExportRouter:
    """Export of the company's data (S8.7) in /api/admin/data-exports"""

    def __init__(self):
        self.router = APIRouter()
        route = self.router
        route.post(
            "",
            response_model=DataResponse[ExportResponse],
            status_code=status.HTTP_202_ACCEPTED,
            summary="Ask for a ZIP with all the company's data",
            responses=RESPONSES_COMMAND,
            dependencies=_EXPORT,
        )(self.create)
        route.get(
            "",
            response_model=PaginatedDataResponse[ExportResponse],
            summary="Get the exports, the last one first",
            responses=RESPONSES_LIST,
            dependencies=_EXPORT,
        )(self.get_all)
        route.get(
            "/{id}",
            response_model=DataResponse[ExportResponse],
            summary="Get an export and its progress",
            responses=RESPONSES_QUERY,
            dependencies=_EXPORT,
        )(self.get_by_id)
        route.get(
            "/{id}/download",
            summary="Download a READY export",
            response_class=FileResponse,
            responses={
                200: {"content": {"application/zip": {}}, "description": "The ZIP"},
                **RESPONSES_QUERY,
            },
            dependencies=_EXPORT,
        )(self.download)

    def create(
        self,
        handler: Injected[RequestDataExportCommandHandler],
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ExportResponse]:
        """Queues the export; the worker writes a ZIP with a CSV per table of
        the company and a manifest, ready a few minutes later. One at a time
        (EXPORT_IN_PROGRESS). Allowed on a cancelled subscription. Audited
        (`data_export.requested`)."""
        result = handler.handle(
            RequestDataExportCommand(
                requested_by_id=user.id,
                requested_by_name=user.display_name,
                request_id=meta.request_id,
            )
        )
        return DataResponse(data=ExportResponse.model_validate(result), meta=meta)

    def get_all(
        self,
        handler: Injected[GetDataExportsQueryHandler],
        query_params: ExportQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[ExportResponse]:
        result = handler.handle(
            GetDataExportsQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[ExportResponse.model_validate(job) for job in result["items"]],
            meta=meta.with_pagination(
                total=result["total"], limit=result["limit"], offset=result["offset"]
            ),
        )

    def get_by_id(
        self,
        id: int,
        handler: Injected[GetDataExportQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ExportResponse]:
        result = handler.handle(GetDataExportQuery(job_id=id))
        return DataResponse(data=ExportResponse.model_validate(result), meta=meta)

    def download(
        self,
        id: int,
        handler: Injected[GetDataExportFileQueryHandler],
    ) -> FileResponse:
        """The ZIP: a CSV per table plus `manifest.json`. EXPORT_NOT_READY while
        it is being written, if it failed or after it expired."""
        job = handler.handle(GetDataExportQuery(job_id=id))
        path = export_file(
            require_tenant("downloading an export").tenant_id, job["file_name"]
        )
        if not path.is_file():
            raise NotFoundError(f"The file of export {id} is no longer there")
        return FileResponse(
            path, media_type="application/zip", filename=f"faclab-export-{id}.zip"
        )
