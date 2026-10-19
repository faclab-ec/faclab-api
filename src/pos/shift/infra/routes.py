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
from src.pos.terminal.app.guard import PosBranchGuard
from src.pos.terminal.app.resolver import TerminalRequest
from src.pos.terminal.infra.dependencies import pos_branch, pos_terminal
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
        terminal: TerminalRequest = Depends(pos_terminal),
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ShiftResponse]:
        """Open a cashier shift in the terminal of `X-Terminal-Id`. A terminal
        has at most one open shift (`SHIFT_ALREADY_OPEN`); the cashier is the
        authenticated user."""
        result = handler.handle(
            OpenShiftCommand(
                terminal=terminal,
                cashier_name=user.display_name,
                user_id=user.id,
                opening_balance=data.opening_balance,
                notes=data.notes,
            )
        )
        return DataResponse(data=ShiftResponse.model_validate(result), meta=meta)

    def close_shift(
        self,
        handler: Injected[CloseShiftCommandHandler],
        guard: Injected[PosBranchGuard],
        shift_id: int,
        data: CloseShiftRequest,
        branch: TerminalRequest = Depends(pos_branch),
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ShiftResponse]:
        """Close an open shift of the branch by recording the actual closing cash balance.

        The system calculates the expected balance and the discrepancy automatically.
        """
        guard.shift(shift_id, branch)
        result = handler.handle(
            CloseShiftCommand(
                shift_id=shift_id,
                closing_balance=data.closing_balance,
                notes=data.notes,
                closed_by=user.display_name,
            )
        )
        return DataResponse(data=ShiftResponse.model_validate(result), meta=meta)

    def get_active_shift(
        self,
        handler: Injected[GetActiveShiftQueryHandler],
        terminal: TerminalRequest = Depends(pos_terminal),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ShiftResponse | None]:
        """Get the open shift of the terminal, or null if it has none."""
        result = handler.handle(GetActiveShiftQuery(terminal=terminal))
        data = ShiftResponse.model_validate(result) if result is not None else None
        return DataResponse(data=data, meta=meta)

    def get_shift(
        self,
        handler: Injected[GetShiftByIdQueryHandler],
        shift_id: int,
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ShiftResponse]:
        """Retrieve a shift by its ID, of a branch the user may enter."""
        result = handler.handle(
            GetShiftByIdQuery(shift_id=shift_id, branch_ids=user.branch_ids)
        )
        return DataResponse(data=ShiftResponse.model_validate(result), meta=meta)

    def get_all_shifts(
        self,
        handler: Injected[GetAllShiftsQueryHandler],
        query_params: ShiftQueryParams = Depends(),
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[ShiftResponse]:
        """List the shifts of the branches the user may enter, newest first,
        optionally by status, branch or terminal. Supports pagination."""
        result = handler.handle(
            GetAllShiftsQuery(
                **query_params.model_dump(exclude_none=True),
                branch_ids=user.branch_ids,
            )
        )
        return PaginatedDataResponse(
            data=[ShiftResponse.model_validate(r) for r in result["items"]],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )
