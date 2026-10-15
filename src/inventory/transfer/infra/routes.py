from fastapi import APIRouter, Depends
from wireup import Injected

from src.auth.domain.entities import AuthenticatedUser
from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import get_current_user, require_permission
from src.inventory.transfer.app.commands.transfer import (
    AddTransferItemCommand,
    AddTransferItemCommandHandler,
    CancelStockTransferCommand,
    CancelStockTransferCommandHandler,
    ConfirmStockTransferCommand,
    ConfirmStockTransferCommandHandler,
    CreateStockTransferCommand,
    CreateStockTransferCommandHandler,
    DeleteStockTransferCommand,
    DeleteStockTransferCommandHandler,
    ReceiveStockTransferCommand,
    ReceiveStockTransferCommandHandler,
    RemoveTransferItemCommand,
    RemoveTransferItemCommandHandler,
    UpdateStockTransferCommand,
    UpdateStockTransferCommandHandler,
    UpdateTransferItemCommand,
    UpdateTransferItemCommandHandler,
)
from src.inventory.transfer.app.queries.transfer import (
    GetAllTransfersQuery,
    GetAllTransfersQueryHandler,
    GetTransferByIdQuery,
    GetTransferByIdQueryHandler,
    GetTransferItemsQuery,
    GetTransferItemsQueryHandler,
)
from src.inventory.transfer.infra.validators import (
    AddTransferItemRequest,
    CreateTransferRequest,
    TransferItemResponse,
    TransferQueryParams,
    TransferResponse,
    UpdateTransferItemRequest,
    UpdateTransferRequest,
)
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import (
    RESPONSES_COMMAND,
    RESPONSES_DELETE,
    RESPONSES_LIST,
    RESPONSES_QUERY,
    DataResponse,
    ListResponse,
    Meta,
    PaginatedDataResponse,
)


class TransferRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        _read = [Depends(require_permission(Permission.STOCK_READ))]
        _write = [Depends(require_permission(Permission.TRANSFER_WRITE))]

        self.router.get(
            "",
            response_model=PaginatedDataResponse[TransferResponse],
            summary="Get all transfers",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_all)
        self.router.post(
            "",
            response_model=DataResponse[TransferResponse],
            summary="Create transfer",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.create)
        self.router.get(
            "/{id}",
            response_model=DataResponse[TransferResponse],
            summary="Get transfer by ID",
            responses=RESPONSES_QUERY,
            dependencies=_read,
        )(self.get_by_id)
        self.router.put(
            "/{id}",
            response_model=DataResponse[TransferResponse],
            summary="Update transfer",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.update)
        self.router.delete(
            "/{id}",
            status_code=204,
            summary="Delete transfer",
            responses=RESPONSES_DELETE,
            dependencies=_write,
        )(self.delete)
        self.router.post(
            "/{id}/confirm",
            response_model=DataResponse[TransferResponse],
            summary="Confirm transfer",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.confirm)
        self.router.post(
            "/{id}/receive",
            response_model=DataResponse[TransferResponse],
            summary="Receive transfer",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.receive)
        self.router.post(
            "/{id}/cancel",
            response_model=DataResponse[TransferResponse],
            summary="Cancel transfer",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.cancel)
        self.router.post(
            "/{id}/items",
            response_model=DataResponse[TransferItemResponse],
            summary="Add item to transfer",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.add_item)
        self.router.get(
            "/{id}/items",
            response_model=ListResponse[TransferItemResponse],
            summary="Get transfer items",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_items)

    def get_all(
        self,
        handler: Injected[GetAllTransfersQueryHandler],
        query_params: TransferQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[TransferResponse]:
        """Get all stock transfers."""
        result = handler.handle(
            GetAllTransfersQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[TransferResponse.model_validate(t) for t in result["items"]],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )

    def create(
        self,
        body: CreateTransferRequest,
        handler: Injected[CreateStockTransferCommandHandler],
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[TransferResponse]:
        """Create a new stock transfer in DRAFT status. The authenticated user is
        recorded as the requester."""
        result = handler.handle(
            CreateStockTransferCommand(
                **body.model_dump(exclude_none=True, by_alias=False),
                requested_by=user.display_name,
            )
        )
        return DataResponse(data=TransferResponse.model_validate(result), meta=meta)

    def get_by_id(
        self,
        id: int,
        handler: Injected[GetTransferByIdQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[TransferResponse]:
        """Get a stock transfer by ID."""
        result = handler.handle(GetTransferByIdQuery(id=id))
        return DataResponse(data=TransferResponse.model_validate(result), meta=meta)

    def update(
        self,
        id: int,
        body: UpdateTransferRequest,
        handler: Injected[UpdateStockTransferCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[TransferResponse]:
        """Update a stock transfer (only DRAFT)."""
        result = handler.handle(
            UpdateStockTransferCommand(
                id=id, **body.model_dump(exclude_none=True, by_alias=False)
            )
        )
        return DataResponse(data=TransferResponse.model_validate(result), meta=meta)

    def delete(
        self,
        id: int,
        handler: Injected[DeleteStockTransferCommandHandler],
    ) -> None:
        """Delete a stock transfer (only DRAFT)."""
        handler.handle(DeleteStockTransferCommand(id=id))

    def confirm(
        self,
        id: int,
        handler: Injected[ConfirmStockTransferCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[TransferResponse]:
        """Confirm a stock transfer — reserves stock at source location."""
        result = handler.handle(ConfirmStockTransferCommand(id=id))
        return DataResponse(data=TransferResponse.model_validate(result), meta=meta)

    def receive(
        self,
        id: int,
        handler: Injected[ReceiveStockTransferCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[TransferResponse]:
        """Receive a stock transfer — creates OUT/IN movements and moves stock."""
        result = handler.handle(ReceiveStockTransferCommand(id=id))
        return DataResponse(data=TransferResponse.model_validate(result), meta=meta)

    def cancel(
        self,
        id: int,
        handler: Injected[CancelStockTransferCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[TransferResponse]:
        """Cancel a stock transfer — releases reservations if CONFIRMED."""
        result = handler.handle(CancelStockTransferCommand(id=id))
        return DataResponse(data=TransferResponse.model_validate(result), meta=meta)

    def add_item(
        self,
        id: int,
        body: AddTransferItemRequest,
        handler: Injected[AddTransferItemCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[TransferItemResponse]:
        """Add an item to a stock transfer."""
        result = handler.handle(
            AddTransferItemCommand(
                transfer_id=id,
                **body.model_dump(exclude_none=True, by_alias=False),
            )
        )
        return DataResponse(data=TransferItemResponse.model_validate(result), meta=meta)

    def get_items(
        self,
        id: int,
        handler: Injected[GetTransferItemsQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> ListResponse[TransferItemResponse]:
        """Get all items for a stock transfer."""
        result = handler.handle(GetTransferItemsQuery(transfer_id=id))
        return ListResponse(
            data=[TransferItemResponse.model_validate(item) for item in result],
            meta=meta,
        )


class TransferItemRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        _write = [Depends(require_permission(Permission.TRANSFER_WRITE))]

        self.router.put(
            "/{id}",
            response_model=DataResponse[TransferItemResponse],
            summary="Update transfer item",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.update)
        self.router.delete(
            "/{id}",
            status_code=204,
            summary="Remove transfer item",
            responses=RESPONSES_DELETE,
            dependencies=_write,
        )(self.remove)

    def update(
        self,
        id: int,
        body: UpdateTransferItemRequest,
        handler: Injected[UpdateTransferItemCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[TransferItemResponse]:
        """Update a transfer item."""
        result = handler.handle(
            UpdateTransferItemCommand(
                id=id, **body.model_dump(exclude_none=True, by_alias=False)
            )
        )
        return DataResponse(data=TransferItemResponse.model_validate(result), meta=meta)

    def remove(
        self,
        id: int,
        handler: Injected[RemoveTransferItemCommandHandler],
    ) -> None:
        """Remove an item from a stock transfer."""
        handler.handle(RemoveTransferItemCommand(id=id))
