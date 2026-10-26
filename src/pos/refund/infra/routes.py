from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from wireup import Injected

from src.auth.domain.entities import AuthenticatedUser
from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import get_current_user, require_permission
from src.pos.refund.app.commands.cancel_refund import (
    CancelRefundCommand,
    CancelRefundCommandHandler,
)
from src.pos.refund.app.commands.create_refund import (
    CreateRefundCommand,
    CreateRefundCommandHandler,
)
from src.pos.refund.app.commands.process_refund import (
    ProcessRefundCommand,
    ProcessRefundCommandHandler,
)
from src.pos.refund.app.queries.get_refunds import (
    GetRefundByIdQuery,
    GetRefundByIdQueryHandler,
    GetRefundsQuery,
    GetRefundsQueryHandler,
)
from src.pos.refund.infra.validators import (
    CreateRefundRequest,
    ProcessRefundRequest,
    RefundDetailResponse,
    RefundQueryParams,
    RefundResponse,
)
from src.pos.terminal.app.guard import PosBranchGuard
from src.pos.terminal.app.resolver import TerminalRequest
from src.pos.terminal.infra.dependencies import pos_branch, pos_terminal
from src.shared.infra.dependencies import get_meta
from src.shared.infra.idempotency.requests import (
    Idempotency,
    IdempotentRequest,
    idempotent_request,
)
from src.shared.infra.validators import (
    RESPONSES_COMMAND,
    RESPONSES_LIST,
    RESPONSES_QUERY,
    DataResponse,
    Meta,
    PaginatedDataResponse,
)


class POSRefundRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        _pos = [Depends(require_permission(Permission.POS_OPERATE))]
        _approve = [Depends(require_permission(Permission.REFUND_APPROVE))]
        # Refund history is read from the back office too (managers, viewers)
        _history = [Depends(require_permission(Permission.REPORT_POS_READ))]

        self.router.post(
            "",
            response_model=DataResponse[RefundDetailResponse],
            status_code=status.HTTP_201_CREATED,
            summary="Create refund",
            responses=RESPONSES_COMMAND,
            dependencies=_pos,
        )(self.create_refund)
        self.router.post(
            "/{refund_id}/process",
            response_model=DataResponse[RefundDetailResponse],
            summary="Process refund",
            responses=RESPONSES_COMMAND,
            dependencies=_approve,
        )(self.process_refund)
        self.router.post(
            "/{refund_id}/cancel",
            response_model=DataResponse[RefundResponse],
            summary="Cancel refund",
            responses=RESPONSES_COMMAND,
            dependencies=_pos,
        )(self.cancel_refund)
        self.router.get(
            "/{refund_id}",
            response_model=DataResponse[RefundDetailResponse],
            summary="Get refund",
            responses=RESPONSES_QUERY,
            dependencies=_history,
        )(self.get_refund)
        self.router.get(
            "",
            response_model=PaginatedDataResponse[RefundResponse],
            summary="List refunds",
            responses=RESPONSES_LIST,
            dependencies=_history,
        )(self.list_refunds)

    def create_refund(
        self,
        handler: Injected[CreateRefundCommandHandler],
        idempotency: Injected[Idempotency],
        refund_input: CreateRefundRequest,
        terminal: TerminalRequest = Depends(pos_terminal),
        user: AuthenticatedUser = Depends(get_current_user),
        idempotent: IdempotentRequest | None = Depends(idempotent_request),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[RefundDetailResponse] | JSONResponse:
        """Create a refund for a confirmed sale, in the open shift of the terminal.

        The terminal must be of the sale's branch (`REFUND_OUTSIDE_BRANCH`).
        Specify the items to refund (partial or total). The refund is created in PENDING
        status and must be processed to register payments and restore inventory.
        Requires `Idempotency-Key`: a retry with it gets the refund created the first time.
        """

        def respond() -> DataResponse[RefundDetailResponse]:
            result = handler.handle(
                CreateRefundCommand(
                    terminal=terminal,
                    original_sale_id=refund_input.original_sale_id,
                    items=[item.model_dump() for item in refund_input.items],
                    reason=refund_input.reason,
                    refunded_by=user.display_name,
                )
            )
            return DataResponse(
                data=RefundDetailResponse.model_validate(result), meta=meta
            )

        return idempotency.run(idempotent, respond)

    def process_refund(
        self,
        handler: Injected[ProcessRefundCommandHandler],
        guard: Injected[PosBranchGuard],
        idempotency: Injected[Idempotency],
        refund_id: int,
        process_input: ProcessRefundRequest,
        branch: TerminalRequest = Depends(pos_branch),
        idempotent: IdempotentRequest | None = Depends(idempotent_request),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[RefundDetailResponse] | JSONResponse:
        """Process a pending refund of the branch by registering refund payments.

        The total of all payments must cover the refund amount. Once processed,
        the stock goes back to the location of the refund's terminal and the refund
        gets its number of the branch.
        Requires `Idempotency-Key`: a retry with it gets the first processing.
        """
        guard.refund(refund_id, branch)

        def respond() -> DataResponse[RefundDetailResponse]:
            result = handler.handle(
                ProcessRefundCommand(
                    refund_id=refund_id,
                    payments=[p.model_dump() for p in process_input.payments],
                )
            )
            return DataResponse(
                data=RefundDetailResponse.model_validate(result), meta=meta
            )

        return idempotency.run(idempotent, respond)

    def cancel_refund(
        self,
        handler: Injected[CancelRefundCommandHandler],
        guard: Injected[PosBranchGuard],
        refund_id: int,
        branch: TerminalRequest = Depends(pos_branch),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[RefundResponse]:
        """Cancel a pending refund of the branch. Only refunds that have not been processed can be cancelled."""
        guard.refund(refund_id, branch)
        result = handler.handle(CancelRefundCommand(refund_id=refund_id))
        return DataResponse(data=RefundResponse.model_validate(result), meta=meta)

    def get_refund(
        self,
        handler: Injected[GetRefundByIdQueryHandler],
        refund_id: int,
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[RefundDetailResponse]:
        """Retrieve a refund by ID, of a branch the user may enter, including its items and payments."""
        result = handler.handle(
            GetRefundByIdQuery(refund_id=refund_id, branch_ids=user.branch_ids)
        )
        return DataResponse(data=RefundDetailResponse.model_validate(result), meta=meta)

    def list_refunds(
        self,
        handler: Injected[GetRefundsQueryHandler],
        meta: Meta = Depends(get_meta),
        params: RefundQueryParams = Depends(),
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> PaginatedDataResponse[RefundResponse]:
        """List the refunds of the branches the user may enter, optionally by
        sale, status, branch or terminal. Supports pagination."""
        result = handler.handle(
            GetRefundsQuery(
                sale_id=params.sale_id,
                status=params.status,
                branch_id=params.branch_id,
                terminal_id=params.terminal_id,
                branch_ids=user.branch_ids,
                limit=params.limit,
                offset=params.offset,
            )
        )
        return PaginatedDataResponse(
            data=[RefundResponse.model_validate(r) for r in result["items"]],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )
