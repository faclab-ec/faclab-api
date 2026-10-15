from fastapi import APIRouter, Depends, status
from wireup import Injected

from src.auth.domain.entities import AuthenticatedUser
from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import get_current_user, require_permission
from src.pos.cash.app.commands.register_cash_movement import (
    RegisterCashMovementCommand,
    RegisterCashMovementCommandHandler,
)
from src.pos.cash.app.queries.get_cash_movements import (
    GetCashMovementsQuery,
    GetCashMovementsQueryHandler,
)
from src.pos.cash.app.queries.get_cash_summary import (
    GetCashSummaryQuery,
    GetCashSummaryQueryHandler,
)
from src.pos.cash.infra.validators import (
    CashMovementQueryParams,
    CashMovementResponse,
    CashSummaryResponse,
    RegisterCashMovementRequest,
)
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import (
    RESPONSES_COMMAND,
    RESPONSES_LIST,
    RESPONSES_QUERY,
    DataResponse,
    Meta,
    PaginatedDataResponse,
)


class POSCashRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        _pos = [Depends(require_permission(Permission.POS_OPERATE))]

        self.router.post(
            "/{shift_id}/cash-movements",
            response_model=DataResponse[CashMovementResponse],
            status_code=status.HTTP_201_CREATED,
            summary="Register cash movement",
            responses=RESPONSES_COMMAND,
            dependencies=_pos,
        )(self.register_cash_movement)
        self.router.get(
            "/{shift_id}/cash-movements",
            response_model=PaginatedDataResponse[CashMovementResponse],
            summary="List cash movements for a shift",
            responses=RESPONSES_LIST,
            dependencies=_pos,
        )(self.get_cash_movements)
        self.router.get(
            "/{shift_id}/cash-summary",
            response_model=DataResponse[CashSummaryResponse],
            summary="Get cash summary for a shift",
            responses=RESPONSES_QUERY,
            dependencies=_pos,
        )(self.get_cash_summary)

    def register_cash_movement(
        self,
        handler: Injected[RegisterCashMovementCommandHandler],
        shift_id: int,
        data: RegisterCashMovementRequest,
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CashMovementResponse]:
        """Register a cash-in or cash-out movement for a shift (e.g. petty cash withdrawal, float top-up)."""
        result = handler.handle(
            RegisterCashMovementCommand(
                shift_id=shift_id,
                type=data.type,
                amount=data.amount,
                reason=data.reason,
                performed_by=user.display_name,
            )
        )
        return DataResponse(data=CashMovementResponse.model_validate(result), meta=meta)

    def get_cash_movements(
        self,
        handler: Injected[GetCashMovementsQueryHandler],
        shift_id: int,
        query_params: CashMovementQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[CashMovementResponse]:
        """List all cash movements recorded during a shift. Supports pagination."""
        result = handler.handle(
            GetCashMovementsQuery(
                shift_id=shift_id,
                limit=query_params.limit,
                offset=query_params.offset,
            )
        )
        return PaginatedDataResponse(
            data=[CashMovementResponse.model_validate(r) for r in result["items"]],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )

    def get_cash_summary(
        self,
        handler: Injected[GetCashSummaryQueryHandler],
        shift_id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CashSummaryResponse]:
        """Get a summary of cash activity for a shift, including totals by payment method and net cash."""
        result = handler.handle(GetCashSummaryQuery(shift_id=shift_id))
        return DataResponse(data=CashSummaryResponse.model_validate(result), meta=meta)
