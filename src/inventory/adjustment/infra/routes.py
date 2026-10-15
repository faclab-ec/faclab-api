from fastapi import APIRouter, Depends
from wireup import Injected

from src.auth.domain.entities import AuthenticatedUser
from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import get_current_user, require_permission
from src.inventory.adjustment.app.commands.adjustment import (
    AddAdjustmentItemCommand,
    AddAdjustmentItemCommandHandler,
    CancelAdjustmentCommand,
    CancelAdjustmentCommandHandler,
    ConfirmAdjustmentCommand,
    ConfirmAdjustmentCommandHandler,
    CreateAdjustmentCommand,
    CreateAdjustmentCommandHandler,
    DeleteAdjustmentCommand,
    DeleteAdjustmentCommandHandler,
    RemoveAdjustmentItemCommand,
    RemoveAdjustmentItemCommandHandler,
    UpdateAdjustmentCommand,
    UpdateAdjustmentCommandHandler,
    UpdateAdjustmentItemCommand,
    UpdateAdjustmentItemCommandHandler,
)
from src.inventory.adjustment.app.queries.adjustment import (
    GetAdjustmentByIdQuery,
    GetAdjustmentByIdQueryHandler,
    GetAdjustmentItemsQuery,
    GetAdjustmentItemsQueryHandler,
    GetAllAdjustmentsQuery,
    GetAllAdjustmentsQueryHandler,
)
from src.inventory.adjustment.infra.validators import (
    AddAdjustmentItemRequest,
    AdjustmentItemResponse,
    AdjustmentQueryParams,
    AdjustmentResponse,
    CreateAdjustmentRequest,
    UpdateAdjustmentItemRequest,
    UpdateAdjustmentRequest,
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


class AdjustmentRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        _read = [Depends(require_permission(Permission.STOCK_READ))]
        _write = [Depends(require_permission(Permission.ADJUSTMENT_WRITE))]

        self.router.get(
            "",
            response_model=PaginatedDataResponse[AdjustmentResponse],
            summary="Get all adjustments",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_all)
        self.router.post(
            "",
            response_model=DataResponse[AdjustmentResponse],
            summary="Create adjustment",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.create)
        self.router.get(
            "/{id}",
            response_model=DataResponse[AdjustmentResponse],
            summary="Get adjustment by ID",
            responses=RESPONSES_QUERY,
            dependencies=_read,
        )(self.get_by_id)
        self.router.put(
            "/{id}",
            response_model=DataResponse[AdjustmentResponse],
            summary="Update adjustment",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.update)
        self.router.delete(
            "/{id}",
            status_code=204,
            summary="Delete adjustment",
            responses=RESPONSES_DELETE,
            dependencies=_write,
        )(self.delete)
        self.router.post(
            "/{id}/confirm",
            response_model=DataResponse[AdjustmentResponse],
            summary="Confirm adjustment",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.confirm)
        self.router.post(
            "/{id}/cancel",
            response_model=DataResponse[AdjustmentResponse],
            summary="Cancel adjustment",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.cancel)
        self.router.post(
            "/{id}/items",
            response_model=DataResponse[AdjustmentItemResponse],
            summary="Add item to adjustment",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.add_item)
        self.router.get(
            "/{id}/items",
            response_model=ListResponse[AdjustmentItemResponse],
            summary="Get adjustment items",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_items)

    def get_all(
        self,
        handler: Injected[GetAllAdjustmentsQueryHandler],
        query_params: AdjustmentQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[AdjustmentResponse]:
        """Get all inventory adjustments."""
        result = handler.handle(
            GetAllAdjustmentsQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[AdjustmentResponse.model_validate(a) for a in result["items"]],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )

    def create(
        self,
        body: CreateAdjustmentRequest,
        handler: Injected[CreateAdjustmentCommandHandler],
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[AdjustmentResponse]:
        """Create a new inventory adjustment in DRAFT status. The authenticated
        user is recorded as the person who adjusted."""
        result = handler.handle(
            CreateAdjustmentCommand(
                **body.model_dump(exclude_none=True, by_alias=False),
                adjusted_by=user.display_name,
            )
        )
        return DataResponse(data=AdjustmentResponse.model_validate(result), meta=meta)

    def get_by_id(
        self,
        id: int,
        handler: Injected[GetAdjustmentByIdQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[AdjustmentResponse]:
        """Get an inventory adjustment by ID."""
        result = handler.handle(GetAdjustmentByIdQuery(id=id))
        return DataResponse(data=AdjustmentResponse.model_validate(result), meta=meta)

    def update(
        self,
        id: int,
        body: UpdateAdjustmentRequest,
        handler: Injected[UpdateAdjustmentCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[AdjustmentResponse]:
        """Update an inventory adjustment (only DRAFT)."""
        result = handler.handle(
            UpdateAdjustmentCommand(
                id=id, **body.model_dump(exclude_none=True, by_alias=False)
            )
        )
        return DataResponse(data=AdjustmentResponse.model_validate(result), meta=meta)

    def delete(
        self,
        id: int,
        handler: Injected[DeleteAdjustmentCommandHandler],
    ) -> None:
        """Delete an inventory adjustment (only DRAFT)."""
        handler.handle(DeleteAdjustmentCommand(id=id))

    def confirm(
        self,
        id: int,
        handler: Injected[ConfirmAdjustmentCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[AdjustmentResponse]:
        """Confirm an inventory adjustment and generate stock movements."""
        result = handler.handle(ConfirmAdjustmentCommand(id=id))
        return DataResponse(data=AdjustmentResponse.model_validate(result), meta=meta)

    def cancel(
        self,
        id: int,
        handler: Injected[CancelAdjustmentCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[AdjustmentResponse]:
        """Cancel an inventory adjustment (only DRAFT)."""
        result = handler.handle(CancelAdjustmentCommand(id=id))
        return DataResponse(data=AdjustmentResponse.model_validate(result), meta=meta)

    def add_item(
        self,
        id: int,
        body: AddAdjustmentItemRequest,
        handler: Injected[AddAdjustmentItemCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[AdjustmentItemResponse]:
        """Add an item to an inventory adjustment."""
        result = handler.handle(
            AddAdjustmentItemCommand(
                adjustment_id=id,
                **body.model_dump(exclude_none=True, by_alias=False),
            )
        )
        return DataResponse(
            data=AdjustmentItemResponse.model_validate(result), meta=meta
        )

    def get_items(
        self,
        id: int,
        handler: Injected[GetAdjustmentItemsQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> ListResponse[AdjustmentItemResponse]:
        """Get all items for an inventory adjustment."""
        result = handler.handle(GetAdjustmentItemsQuery(adjustment_id=id))
        return ListResponse(
            data=[AdjustmentItemResponse.model_validate(item) for item in result],
            meta=meta,
        )


class AdjustmentItemRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        _write = [Depends(require_permission(Permission.ADJUSTMENT_WRITE))]

        self.router.put(
            "/{id}",
            response_model=DataResponse[AdjustmentItemResponse],
            summary="Update adjustment item",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.update)
        self.router.delete(
            "/{id}",
            status_code=204,
            summary="Remove adjustment item",
            responses=RESPONSES_DELETE,
            dependencies=_write,
        )(self.remove)

    def update(
        self,
        id: int,
        body: UpdateAdjustmentItemRequest,
        handler: Injected[UpdateAdjustmentItemCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[AdjustmentItemResponse]:
        """Update an adjustment item."""
        result = handler.handle(
            UpdateAdjustmentItemCommand(
                id=id, **body.model_dump(exclude_none=True, by_alias=False)
            )
        )
        return DataResponse(
            data=AdjustmentItemResponse.model_validate(result), meta=meta
        )

    def remove(
        self,
        id: int,
        handler: Injected[RemoveAdjustmentItemCommandHandler],
    ) -> None:
        """Remove an item from an inventory adjustment."""
        handler.handle(RemoveAdjustmentItemCommand(id=id))
