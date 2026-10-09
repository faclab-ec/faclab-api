from fastapi import APIRouter, Depends
from wireup import Injected

from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import require_permission
from src.reports.dashboard.app.queries.dashboard import (
    GetDashboardQuery,
    GetDashboardQueryHandler,
)
from src.reports.dashboard.infra.validators import (
    DashboardQueryParams,
    DashboardResponse,
)
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import RESPONSES_QUERY, DataResponse, Meta


class DashboardRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        self.router.get(
            "",
            response_model=DataResponse[DashboardResponse],
            summary="Home dashboard",
            responses=RESPONSES_QUERY,
            dependencies=[
                Depends(
                    require_permission(
                        Permission.REPORT_INVENTORY_READ, Permission.ALERT_READ
                    )
                )
            ],
        )(self.dashboard)

    def dashboard(
        self,
        handler: Injected[GetDashboardQueryHandler],
        query_params: DashboardQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[DashboardResponse]:
        """Inventory value, warehouse summary and alert counts in one call."""
        result = handler.handle(
            GetDashboardQuery(expiring_days=query_params.expiring_days)
        )
        return DataResponse(data=DashboardResponse.model_validate(result), meta=meta)
