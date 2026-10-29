from fastapi import APIRouter, Depends
from wireup import Injected

from src.audit.app.queries.audit_log import ListAuditLogQuery, ListAuditLogQueryHandler
from src.audit.infra.validators import AuditEntryResponse, AuditLogQueryParams
from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import require_permission
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import RESPONSES_LIST, Meta, PaginatedDataResponse


class AuditLogRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        self.router.get(
            "",
            response_model=PaginatedDataResponse[AuditEntryResponse],
            summary="Audit log",
            responses=RESPONSES_LIST,
            dependencies=[Depends(require_permission(Permission.AUDIT_READ))],
        )(self.get_all)

    def get_all(
        self,
        handler: Injected[ListAuditLogQueryHandler],
        query_params: AuditLogQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[AuditEntryResponse]:
        """
        Sensitive operations of the tenant, newest first: who did them (from
        the token), on what resource, and the relevant fields before and after.
        Filters by date range, user, action, resource and branch.
        """
        result = handler.handle(
            ListAuditLogQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[AuditEntryResponse.model_validate(item) for item in result["items"]],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )
