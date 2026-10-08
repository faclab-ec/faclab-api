from fastapi import APIRouter, Depends, status
from wireup import Injected

from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import require_permission
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
from src.shared.infra.dependencies import get_meta
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
            dependencies=_pos,
        )(self.get_refund)
        self.router.get(
            "",
            response_model=PaginatedDataResponse[RefundResponse],
            summary="List refunds",
            responses=RESPONSES_LIST,
            dependencies=_pos,
        )(self.list_refunds)

    def create_refund(
        self,
        handler: Injected[CreateRefundCommandHandler],
        refund_input: CreateRefundRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[RefundDetailResponse]:
        """Create a refund for a confirmed sale.

        Specify the items to refund (partial or total). The refund is created in PENDING
        status and must be processed to register payments and restore inventory.
        """
        result = handler.handle(
            CreateRefundCommand(
                original_sale_id=refund_input.original_sale_id,
                items=[item.model_dump() for item in refund_input.items],
                reason=refund_input.reason,
                refunded_by=refund_input.refunded_by,
            )
        )
        return DataResponse(data=RefundDetailResponse.model_validate(result), meta=meta)

    def process_refund(
        self,
        handler: Injected[ProcessRefundCommandHandler],
        refund_id: int,
        process_input: ProcessRefundRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[RefundDetailResponse]:
        """Process a pending refund by registering refund payments.

        The total of all payments must cover the refund amount. Once processed,
        inventory IN movements are created to restore stock.
        """
        result = handler.handle(
            ProcessRefundCommand(
                refund_id=refund_id,
                payments=[p.model_dump() for p in process_input.payments],
            )
        )
        return DataResponse(data=RefundDetailResponse.model_validate(result), meta=meta)

    def cancel_refund(
        self,
        handler: Injected[CancelRefundCommandHandler],
        refund_id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[RefundResponse]:
        """Cancel a pending refund. Only refunds that have not been processed can be cancelled."""
        result = handler.handle(CancelRefundCommand(refund_id=refund_id))
        return DataResponse(data=RefundResponse.model_validate(result), meta=meta)

    def get_refund(
        self,
        handler: Injected[GetRefundByIdQueryHandler],
        refund_id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[RefundDetailResponse]:
        """Retrieve a refund by ID, including its items and payments."""
        result = handler.handle(GetRefundByIdQuery(refund_id=refund_id))
        return DataResponse(data=RefundDetailResponse.model_validate(result), meta=meta)

    def list_refunds(
        self,
        handler: Injected[GetRefundsQueryHandler],
        meta: Meta = Depends(get_meta),
        params: RefundQueryParams = Depends(),
    ) -> PaginatedDataResponse[RefundResponse]:
        """List refunds with optional filtering by sale ID or status. Supports pagination."""
        result = handler.handle(
            GetRefundsQuery(
                sale_id=params.sale_id,
                status=params.status,
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
