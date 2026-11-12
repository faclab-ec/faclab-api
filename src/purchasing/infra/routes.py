from fastapi import APIRouter, Depends
from wireup import Injected

from src.auth.domain.entities import AuthenticatedUser
from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import get_current_user, require_permission
from src.purchasing.app.commands.purchase_order import (
    CancelPurchaseOrderCommand,
    CancelPurchaseOrderCommandHandler,
    CreatePurchaseOrderCommand,
    CreatePurchaseOrderCommandHandler,
    DeletePurchaseOrderCommand,
    DeletePurchaseOrderCommandHandler,
    SendPurchaseOrderCommand,
    SendPurchaseOrderCommandHandler,
    UpdatePurchaseOrderCommand,
    UpdatePurchaseOrderCommandHandler,
)
from src.purchasing.app.commands.purchase_order_item import (
    AddPurchaseOrderItemCommand,
    AddPurchaseOrderItemCommandHandler,
    RemovePurchaseOrderItemCommand,
    RemovePurchaseOrderItemCommandHandler,
    UpdatePurchaseOrderItemCommand,
    UpdatePurchaseOrderItemCommandHandler,
)
from src.purchasing.app.commands.purchase_receipt import (
    CreatePurchaseReceiptCommand,
    CreatePurchaseReceiptCommandHandler,
    ReceiveItemInput,
)
from src.purchasing.app.commands.supplier_return import (
    AddSupplierReturnItemCommand,
    AddSupplierReturnItemCommandHandler,
    ConfirmSupplierReturnCommand,
    ConfirmSupplierReturnCommandHandler,
    CreateSupplierReturnCommand,
    CreateSupplierReturnCommandHandler,
    DeleteSupplierReturnCommand,
    DeleteSupplierReturnCommandHandler,
    RemoveSupplierReturnItemCommand,
    RemoveSupplierReturnItemCommandHandler,
    UpdateSupplierReturnCommand,
    UpdateSupplierReturnCommandHandler,
    UpdateSupplierReturnItemCommand,
    UpdateSupplierReturnItemCommandHandler,
)
from src.purchasing.app.queries.purchase_order import (
    GetAllPurchaseOrdersQuery,
    GetAllPurchaseOrdersQueryHandler,
    GetPurchaseOrderByIdQuery,
    GetPurchaseOrderByIdQueryHandler,
)
from src.purchasing.app.queries.purchase_order_item import (
    GetPurchaseOrderItemsByPOQuery,
    GetPurchaseOrderItemsByPOQueryHandler,
)
from src.purchasing.app.queries.purchase_receipt import (
    GetReceiptsByPurchaseOrderQuery,
    GetReceiptsByPurchaseOrderQueryHandler,
)
from src.purchasing.app.queries.supplier_return import (
    GetSupplierReturnByIdQuery,
    GetSupplierReturnByIdQueryHandler,
    GetSupplierReturnItemsQuery,
    GetSupplierReturnItemsQueryHandler,
    GetSupplierReturnsQuery,
    GetSupplierReturnsQueryHandler,
)
from src.purchasing.infra.validators import (
    AddSupplierReturnItemRequest,
    ConfirmSupplierReturnRequest,
    CreatePurchaseReceiptRequest,
    CreateSupplierReturnRequest,
    PurchaseOrderItemRequest,
    PurchaseOrderItemResponse,
    PurchaseOrderItemUpdateRequest,
    PurchaseOrderQueryParams,
    PurchaseOrderRequest,
    PurchaseOrderResponse,
    PurchaseReceiptResponse,
    SupplierReturnItemResponse,
    SupplierReturnQueryParams,
    SupplierReturnResponse,
    UpdateSupplierReturnItemRequest,
    UpdateSupplierReturnRequest,
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


class PurchaseOrderRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        _read = [Depends(require_permission(Permission.PURCHASE_READ))]
        _write = [Depends(require_permission(Permission.PURCHASE_WRITE))]
        _confirm = [Depends(require_permission(Permission.PURCHASE_CONFIRM))]
        _receive = [Depends(require_permission(Permission.PURCHASE_RECEIVE))]

        self.router.post(
            "",
            response_model=DataResponse[PurchaseOrderResponse],
            summary="Create purchase order",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.create)
        self.router.put(
            "/{id}",
            response_model=DataResponse[PurchaseOrderResponse],
            summary="Update purchase order",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.update)
        self.router.delete(
            "/{id}",
            summary="Delete purchase order",
            responses=RESPONSES_DELETE,
            dependencies=_write,
        )(self.delete)
        self.router.get(
            "",
            response_model=PaginatedDataResponse[PurchaseOrderResponse],
            summary="Get all purchase orders",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_all)
        self.router.get(
            "/{id}",
            response_model=DataResponse[PurchaseOrderResponse],
            summary="Get purchase order by ID",
            responses=RESPONSES_QUERY,
            dependencies=_read,
        )(self.get_by_id)
        self.router.post(
            "/{id}/send",
            response_model=DataResponse[PurchaseOrderResponse],
            summary="Send purchase order to supplier",
            responses=RESPONSES_COMMAND,
            dependencies=_confirm,
        )(self.send)
        self.router.post(
            "/{id}/cancel",
            response_model=DataResponse[PurchaseOrderResponse],
            summary="Cancel purchase order",
            responses=RESPONSES_COMMAND,
            dependencies=_confirm,
        )(self.cancel)
        self.router.post(
            "/{id}/receive",
            response_model=DataResponse[PurchaseReceiptResponse],
            summary="Receive goods for purchase order",
            responses=RESPONSES_COMMAND,
            dependencies=_receive,
        )(self.receive)
        self.router.get(
            "/{id}/items",
            response_model=ListResponse[PurchaseOrderItemResponse],
            summary="Get items for a purchase order",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_items)
        self.router.get(
            "/{id}/receipts",
            response_model=ListResponse[PurchaseReceiptResponse],
            summary="Get receipts for a purchase order",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_receipts)

    def create(
        self,
        handler: Injected[CreatePurchaseOrderCommandHandler],
        body: PurchaseOrderRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[PurchaseOrderResponse]:
        """Creates a new purchase order."""
        result = handler.handle(
            CreatePurchaseOrderCommand(**body.model_dump(exclude_none=True))
        )
        return DataResponse(
            data=PurchaseOrderResponse.model_validate(result), meta=meta
        )

    def update(
        self,
        handler: Injected[UpdatePurchaseOrderCommandHandler],
        id: int,
        body: PurchaseOrderRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[PurchaseOrderResponse]:
        """Updates a purchase order (only DRAFT status)."""
        result = handler.handle(
            UpdatePurchaseOrderCommand(id=id, **body.model_dump(exclude_none=True))
        )
        return DataResponse(
            data=PurchaseOrderResponse.model_validate(result), meta=meta
        )

    def delete(
        self,
        handler: Injected[DeletePurchaseOrderCommandHandler],
        id: int,
    ) -> None:
        """Deletes a purchase order (only DRAFT status)."""
        handler.handle(DeletePurchaseOrderCommand(id=id))

    def get_all(
        self,
        handler: Injected[GetAllPurchaseOrdersQueryHandler],
        query_params: PurchaseOrderQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[PurchaseOrderResponse]:
        """Retrieves all purchase orders."""
        result = handler.handle(
            GetAllPurchaseOrdersQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[PurchaseOrderResponse.model_validate(po) for po in result["items"]],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )

    def get_by_id(
        self,
        handler: Injected[GetPurchaseOrderByIdQueryHandler],
        id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[PurchaseOrderResponse]:
        """Retrieves a purchase order by ID."""
        result = handler.handle(GetPurchaseOrderByIdQuery(id=id))
        return DataResponse(
            data=PurchaseOrderResponse.model_validate(result), meta=meta
        )

    def send(
        self,
        handler: Injected[SendPurchaseOrderCommandHandler],
        id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[PurchaseOrderResponse]:
        """Sends a purchase order to the supplier."""
        result = handler.handle(SendPurchaseOrderCommand(id=id))
        return DataResponse(
            data=PurchaseOrderResponse.model_validate(result), meta=meta
        )

    def cancel(
        self,
        handler: Injected[CancelPurchaseOrderCommandHandler],
        id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[PurchaseOrderResponse]:
        """Cancels a purchase order."""
        result = handler.handle(CancelPurchaseOrderCommand(id=id))
        return DataResponse(
            data=PurchaseOrderResponse.model_validate(result), meta=meta
        )

    def receive(
        self,
        handler: Injected[CreatePurchaseReceiptCommandHandler],
        id: int,
        body: CreatePurchaseReceiptRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[PurchaseReceiptResponse]:
        """Registers a goods receipt for a purchase order."""
        items = [
            ReceiveItemInput(
                purchase_order_item_id=item.purchase_order_item_id,
                quantity_received=item.quantity_received,
                location_id=item.location_id,
                lot_number=item.lot_number,
                serial_numbers=item.serial_numbers,
            )
            for item in body.items
        ]
        result = handler.handle(
            CreatePurchaseReceiptCommand(
                purchase_order_id=id,
                items=items,
                notes=body.notes,
                received_at=body.received_at,
                supplier_invoice_number=body.supplier_invoice_number,
            )
        )
        return DataResponse(
            data=PurchaseReceiptResponse.model_validate(result), meta=meta
        )

    def get_items(
        self,
        handler: Injected[GetPurchaseOrderItemsByPOQueryHandler],
        id: int,
        meta: Meta = Depends(get_meta),
    ) -> ListResponse[PurchaseOrderItemResponse]:
        """Retrieves all items for a purchase order."""
        result = handler.handle(GetPurchaseOrderItemsByPOQuery(purchase_order_id=id))
        return ListResponse(
            data=[PurchaseOrderItemResponse.model_validate(item) for item in result],
            meta=meta,
        )

    def get_receipts(
        self,
        handler: Injected[GetReceiptsByPurchaseOrderQueryHandler],
        id: int,
        meta: Meta = Depends(get_meta),
    ) -> ListResponse[PurchaseReceiptResponse]:
        """Retrieves all receipts for a purchase order."""
        result = handler.handle(GetReceiptsByPurchaseOrderQuery(purchase_order_id=id))
        return ListResponse(
            data=[PurchaseReceiptResponse.model_validate(r) for r in result],
            meta=meta,
        )


class POItemRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        _write = [Depends(require_permission(Permission.PURCHASE_WRITE))]

        self.router.post(
            "",
            response_model=DataResponse[PurchaseOrderItemResponse],
            summary="Add item to purchase order",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.add)
        self.router.put(
            "/{id}",
            response_model=DataResponse[PurchaseOrderItemResponse],
            summary="Update purchase order item",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.update)
        self.router.delete(
            "/{id}",
            summary="Remove purchase order item",
            responses=RESPONSES_DELETE,
            dependencies=_write,
        )(self.remove)

    def add(
        self,
        handler: Injected[AddPurchaseOrderItemCommandHandler],
        body: PurchaseOrderItemRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[PurchaseOrderItemResponse]:
        """Adds an item to a purchase order."""
        result = handler.handle(
            AddPurchaseOrderItemCommand(**body.model_dump(exclude_none=True))
        )
        return DataResponse(
            data=PurchaseOrderItemResponse.model_validate(result), meta=meta
        )

    def update(
        self,
        handler: Injected[UpdatePurchaseOrderItemCommandHandler],
        id: int,
        body: PurchaseOrderItemUpdateRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[PurchaseOrderItemResponse]:
        """Updates a purchase order item."""
        result = handler.handle(
            UpdatePurchaseOrderItemCommand(id=id, **body.model_dump(exclude_none=True))
        )
        return DataResponse(
            data=PurchaseOrderItemResponse.model_validate(result), meta=meta
        )

    def remove(
        self,
        handler: Injected[RemovePurchaseOrderItemCommandHandler],
        id: int,
    ) -> None:
        """Removes an item from a purchase order."""
        handler.handle(RemovePurchaseOrderItemCommand(id=id))


class SupplierReturnRouter:
    """Goods of a received purchase order back to the supplier (S5.7)"""

    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        _read = [Depends(require_permission(Permission.PURCHASE_READ))]
        _write = [Depends(require_permission(Permission.PURCHASE_WRITE))]
        _confirm = [Depends(require_permission(Permission.PURCHASE_CONFIRM))]

        self.router.post(
            "",
            response_model=DataResponse[SupplierReturnResponse],
            summary="Create a supplier return (draft) for a received order",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.create)
        self.router.get(
            "",
            response_model=PaginatedDataResponse[SupplierReturnResponse],
            summary="List supplier returns, newest first",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_all)
        self.router.get(
            "/{id}",
            response_model=DataResponse[SupplierReturnResponse],
            summary="Get a supplier return with its VAT by rate",
            responses=RESPONSES_QUERY,
            dependencies=_read,
        )(self.get_by_id)
        self.router.put(
            "/{id}",
            response_model=DataResponse[SupplierReturnResponse],
            summary="Update a draft supplier return",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.update)
        self.router.delete(
            "/{id}",
            summary="Delete a draft supplier return",
            responses=RESPONSES_DELETE,
            dependencies=_write,
        )(self.delete)
        self.router.post(
            "/{id}/confirm",
            response_model=DataResponse[SupplierReturnResponse],
            summary="Confirm a supplier return: stock out and accounts payable "
            "credited",
            responses=RESPONSES_COMMAND,
            dependencies=_confirm,
        )(self.confirm)
        self.router.get(
            "/{id}/items",
            response_model=ListResponse[SupplierReturnItemResponse],
            summary="Get the items of a supplier return",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_items)
        self.router.post(
            "/{id}/items",
            response_model=DataResponse[SupplierReturnItemResponse],
            summary="Add a received order line to a draft supplier return",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.add_item)

    def create(
        self,
        handler: Injected[CreateSupplierReturnCommandHandler],
        body: CreateSupplierReturnRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SupplierReturnResponse]:
        """A draft return of an order with goods received, numbered
        `DP-2026-0001`; `PURCHASE_ORDER_NOT_RETURNABLE` if it has none left."""
        result = handler.handle(
            CreateSupplierReturnCommand(
                purchase_order_id=body.purchase_order_id, notes=body.notes
            )
        )
        return DataResponse(
            data=SupplierReturnResponse.model_validate(result), meta=meta
        )

    def get_all(
        self,
        handler: Injected[GetSupplierReturnsQueryHandler],
        query_params: SupplierReturnQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[SupplierReturnResponse]:
        result = handler.handle(
            GetSupplierReturnsQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[SupplierReturnResponse.model_validate(r) for r in result["items"]],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )

    def get_by_id(
        self,
        handler: Injected[GetSupplierReturnByIdQueryHandler],
        id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SupplierReturnResponse]:
        result = handler.handle(GetSupplierReturnByIdQuery(id=id))
        return DataResponse(
            data=SupplierReturnResponse.model_validate(result), meta=meta
        )

    def update(
        self,
        handler: Injected[UpdateSupplierReturnCommandHandler],
        id: int,
        body: UpdateSupplierReturnRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SupplierReturnResponse]:
        result = handler.handle(UpdateSupplierReturnCommand(id=id, notes=body.notes))
        return DataResponse(
            data=SupplierReturnResponse.model_validate(result), meta=meta
        )

    def delete(
        self,
        handler: Injected[DeleteSupplierReturnCommandHandler],
        id: int,
    ) -> None:
        handler.handle(DeleteSupplierReturnCommand(id=id))

    def confirm(
        self,
        handler: Injected[ConfirmSupplierReturnCommandHandler],
        id: int,
        body: ConfirmSupplierReturnRequest,
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SupplierReturnResponse]:
        """The goods leave the stock at each location's average cost
        (`INSUFFICIENT_STOCK` if not available) and the total, with VAT, is
        credited to the supplier's open accounts payable: the order's first,
        then by due date. What doesn't fit is `refundDue`."""
        result = handler.handle(
            ConfirmSupplierReturnCommand(
                id=id,
                supplier_credit_note_number=body.supplier_credit_note_number,
                confirmed_by=user.display_name,
            )
        )
        return DataResponse(
            data=SupplierReturnResponse.model_validate(result), meta=meta
        )

    def get_items(
        self,
        handler: Injected[GetSupplierReturnItemsQueryHandler],
        id: int,
        meta: Meta = Depends(get_meta),
    ) -> ListResponse[SupplierReturnItemResponse]:
        result = handler.handle(GetSupplierReturnItemsQuery(supplier_return_id=id))
        return ListResponse(
            data=[SupplierReturnItemResponse.model_validate(i) for i in result],
            meta=meta,
        )

    def add_item(
        self,
        handler: Injected[AddSupplierReturnItemCommandHandler],
        id: int,
        body: AddSupplierReturnItemRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SupplierReturnItemResponse]:
        """A line of the return's order; at most what it received minus what
        went back (`EXCEEDS_RETURNABLE_QUANTITY`)."""
        result = handler.handle(
            AddSupplierReturnItemCommand(
                supplier_return_id=id,
                purchase_order_item_id=body.purchase_order_item_id,
                quantity=body.quantity,
                location_id=body.location_id,
            )
        )
        return DataResponse(
            data=SupplierReturnItemResponse.model_validate(result), meta=meta
        )


class SupplierReturnItemRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        _write = [Depends(require_permission(Permission.PURCHASE_WRITE))]

        self.router.put(
            "/{id}",
            response_model=DataResponse[SupplierReturnItemResponse],
            summary="Update an item of a draft supplier return",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.update)
        self.router.delete(
            "/{id}",
            summary="Remove an item from a draft supplier return",
            responses=RESPONSES_DELETE,
            dependencies=_write,
        )(self.remove)

    def update(
        self,
        handler: Injected[UpdateSupplierReturnItemCommandHandler],
        id: int,
        body: UpdateSupplierReturnItemRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SupplierReturnItemResponse]:
        result = handler.handle(
            UpdateSupplierReturnItemCommand(
                id=id, quantity=body.quantity, location_id=body.location_id
            )
        )
        return DataResponse(
            data=SupplierReturnItemResponse.model_validate(result), meta=meta
        )

    def remove(
        self,
        handler: Injected[RemoveSupplierReturnItemCommandHandler],
        id: int,
    ) -> None:
        handler.handle(RemoveSupplierReturnItemCommand(id=id))
