"""POS routes for Shifts"""

from fastapi import APIRouter, Depends, status
from wireup import Injected

from src.auth.domain.entities import AuthenticatedUser
from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import get_current_user, require_permission
from src.pos.shift.app.commands.close_shift import (
    CloseShiftCommand,
    CloseShiftCommandHandler,
)
from src.pos.shift.app.commands.open_shift import (
    OpenShiftCommand,
    OpenShiftCommandHandler,
)
from src.pos.shift.app.queries.get_shifts import (
    GetActiveShiftQuery,
    GetActiveShiftQueryHandler,
    GetAllShiftsQuery,
    GetAllShiftsQueryHandler,
    GetShiftByIdQuery,
    GetShiftByIdQueryHandler,
)
from src.pos.shift.infra.validators import (
    CloseShiftRequest,
    OpenShiftRequest,
    ShiftQueryParams,
    ShiftResponse,
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


class POSShiftRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        _pos = [Depends(require_permission(Permission.POS_OPERATE))]
        # Shift history is read from the back office too (managers, viewers)
        _history = [Depends(require_permission(Permission.REPORT_POS_READ))]

        self.router.post(
            "/open",
            response_model=DataResponse[ShiftResponse],
            status_code=status.HTTP_201_CREATED,
            summary="Open shift",
            responses=RESPONSES_COMMAND,
            dependencies=_pos,
        )(self.open_shift)
        self.router.post(
            "/{shift_id}/close",
            response_model=DataResponse[ShiftResponse],
            summary="Close shift",
            responses=RESPONSES_COMMAND,
            dependencies=_pos,
        )(self.close_shift)
        self.router.get(
            "/active",
            response_model=DataResponse[ShiftResponse | None],
            summary="Get active shift",
            responses=RESPONSES_QUERY,
            dependencies=_pos,
        )(self.get_active_shift)
        self.router.get(
            "/{shift_id}",
            response_model=DataResponse[ShiftResponse],
            summary="Get shift by ID",
            responses=RESPONSES_QUERY,
            dependencies=_history,
        )(self.get_shift)
        self.router.get(
            "",
            response_model=PaginatedDataResponse[ShiftResponse],
            summary="List all shifts",
            responses=RESPONSES_LIST,
            dependencies=_history,
        )(self.get_all_shifts)

    def open_shift(
        self,
        handler: Injected[OpenShiftCommandHandler],
        data: OpenShiftRequest,
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ShiftResponse]:
        """Open a new cashier shift. Only one shift can be active at a time."""
        result = handler.handle(
            OpenShiftCommand(
                cashier_name=user.display_name,
                opening_balance=data.opening_balance,
                notes=data.notes,
            )
        )
        return DataResponse(data=ShiftResponse.model_validate(result), meta=meta)

    def close_shift(
        self,
        handler: Injected[CloseShiftCommandHandler],
        shift_id: int,
        data: CloseShiftRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ShiftResponse]:
        """Close an open shift by recording the actual closing cash balance.

        The system calculates the expected balance and the discrepancy automatically.
        """
        result = handler.handle(
            CloseShiftCommand(
                shift_id=shift_id,
                closing_balance=data.closing_balance,
                notes=data.notes,
            )
        )
        return DataResponse(data=ShiftResponse.model_validate(result), meta=meta)

    def get_active_shift(
        self,
        handler: Injected[GetActiveShiftQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ShiftResponse | None]:
        """Get the currently active (open) shift, or null if no shift is open."""
        result = handler.handle(GetActiveShiftQuery())
        data = ShiftResponse.model_validate(result) if result is not None else None
        return DataResponse(data=data, meta=meta)

    def get_shift(
        self,
        handler: Injected[GetShiftByIdQueryHandler],
        shift_id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ShiftResponse]:
        """Retrieve a shift by its ID."""
        result = handler.handle(GetShiftByIdQuery(shift_id=shift_id))
        return DataResponse(data=ShiftResponse.model_validate(result), meta=meta)

    def get_all_shifts(
        self,
        handler: Injected[GetAllShiftsQueryHandler],
        query_params: ShiftQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[ShiftResponse]:
        """List all shifts with optional filtering by status. Supports pagination."""
        result = handler.handle(
            GetAllShiftsQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[ShiftResponse.model_validate(r) for r in result["items"]],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )
