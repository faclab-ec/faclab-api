from fastapi import APIRouter, Depends
from wireup import Injected

from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import require_branch, require_permission
from src.pricing.app.commands.items import (
    CreatePriceListItemCommand,
    CreatePriceListItemCommandHandler,
    DeletePriceListItemCommand,
    DeletePriceListItemCommandHandler,
    UpdatePriceListItemCommand,
    UpdatePriceListItemCommandHandler,
)
from src.pricing.app.commands.price_lists import (
    CreatePriceListCommand,
    CreatePriceListCommandHandler,
    DeletePriceListCommand,
    DeletePriceListCommandHandler,
    UpdatePriceListCommand,
    UpdatePriceListCommandHandler,
)
from src.pricing.app.queries.price_lists import (
    GetPriceListItemsQuery,
    GetPriceListItemsQueryHandler,
    GetPriceListQuery,
    GetPriceListQueryHandler,
    GetPriceListsQuery,
    GetPriceListsQueryHandler,
)
from src.pricing.app.queries.resolve import (
    PriceLineInput,
    ResolvePricesQuery,
    ResolvePricesQueryHandler,
)
from src.pricing.infra.validators import (
    PriceListItemQueryParams,
    PriceListItemRequest,
    PriceListItemResponse,
    PriceListItemUpdateRequest,
    PriceListQueryParams,
    PriceListRequest,
    PriceListResponse,
    ResolvedPriceResponse,
    ResolvePricesRequest,
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

# Who changes a product's price changes its lists
_READ = [Depends(require_permission(Permission.PRODUCT_READ))]
_WRITE = [Depends(require_permission(Permission.PRODUCT_WRITE))]


class PriceListRouter:
    """Listas de precios (S5.3) en /api/admin/price-lists"""

    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        self.router.get(
            "",
            response_model=PaginatedDataResponse[PriceListResponse],
            summary="Get the price lists",
            responses=RESPONSES_LIST,
            dependencies=_READ,
        )(self.get_all)
        self.router.post(
            "",
            response_model=DataResponse[PriceListResponse],
            summary="Create a price list",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.create)
        self.router.get(
            "/{id}",
            response_model=DataResponse[PriceListResponse],
            summary="Get a price list",
            responses=RESPONSES_QUERY,
            dependencies=_READ,
        )(self.get_by_id)
        self.router.put(
            "/{id}",
            response_model=DataResponse[PriceListResponse],
            summary="Update a price list",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.update)
        self.router.delete(
            "/{id}",
            summary="Delete a price list",
            responses=RESPONSES_DELETE,
            dependencies=_WRITE,
        )(self.delete)
        self.router.get(
            "/{id}/items",
            response_model=PaginatedDataResponse[PriceListItemResponse],
            summary="Get the prices of a list",
            responses=RESPONSES_LIST,
            dependencies=_READ,
        )(self.get_items)
        self.router.post(
            "/{id}/items",
            response_model=DataResponse[PriceListItemResponse],
            summary="Add a price to a list",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.create_item)
        self.router.put(
            "/{id}/items/{item_id}",
            response_model=DataResponse[PriceListItemResponse],
            summary="Update a price of a list",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.update_item)
        self.router.delete(
            "/{id}/items/{item_id}",
            summary="Delete a price of a list",
            responses=RESPONSES_DELETE,
            dependencies=_WRITE,
        )(self.delete_item)

    def get_all(
        self,
        handler: Injected[GetPriceListsQueryHandler],
        query_params: PriceListQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[PriceListResponse]:
        """The company's price lists: the general one first, then by name."""
        result = handler.handle(
            GetPriceListsQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[PriceListResponse.model_validate(p) for p in result["items"]],
            meta=meta.with_pagination(
                total=result["total"], limit=result["limit"], offset=result["offset"]
            ),
        )

    def create(
        self,
        body: PriceListRequest,
        handler: Injected[CreatePriceListCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[PriceListResponse]:
        """Creates a list. Its name is unique in the company
        (`PRICE_LIST_ALREADY_EXISTS`, 409)."""
        result = handler.handle(CreatePriceListCommand(**dict(body)))
        return DataResponse(data=PriceListResponse.model_validate(result), meta=meta)

    def get_by_id(
        self,
        id: int,
        handler: Injected[GetPriceListQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[PriceListResponse]:
        result = handler.handle(GetPriceListQuery(price_list_id=id))
        return DataResponse(data=PriceListResponse.model_validate(result), meta=meta)

    def update(
        self,
        id: int,
        body: PriceListRequest,
        handler: Injected[UpdatePriceListCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[PriceListResponse]:
        """Replaces a list's data. The general list stays active and without
        validity dates (`DEFAULT_PRICE_LIST_LOCKED`, 400)."""
        result = handler.handle(UpdatePriceListCommand(price_list_id=id, **dict(body)))
        return DataResponse(data=PriceListResponse.model_validate(result), meta=meta)

    def delete(self, id: int, handler: Injected[DeletePriceListCommandHandler]) -> None:
        """Deletes a list and its prices. One assigned to a customer or a branch
        answers `RECORD_IN_USE` (409); the general one can't be deleted."""
        handler.handle(DeletePriceListCommand(price_list_id=id))

    def get_items(
        self,
        id: int,
        handler: Injected[GetPriceListItemsQueryHandler],
        query_params: PriceListItemQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[PriceListItemResponse]:
        """The prices of a list by product, presentation and minimum quantity."""
        result = handler.handle(
            GetPriceListItemsQuery(
                price_list_id=id, **query_params.model_dump(exclude_none=True)
            )
        )
        return PaginatedDataResponse(
            data=[PriceListItemResponse.model_validate(i) for i in result["items"]],
            meta=meta.with_pagination(
                total=result["total"], limit=result["limit"], offset=result["offset"]
            ),
        )

    def create_item(
        self,
        id: int,
        body: PriceListItemRequest,
        handler: Injected[CreatePriceListItemCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[PriceListItemResponse]:
        """Prices a presentation of a product in the list from a quantity. One
        price per presentation and minimum quantity
        (`PRICE_LIST_ITEM_ALREADY_EXISTS`, 409); the general list only takes
        tiers (`DEFAULT_PRICE_LIST_BASE_PRICE`, 400)."""
        result = handler.handle(
            # dict() keeps the Decimals that model_dump() turns into floats
            CreatePriceListItemCommand(price_list_id=id, **dict(body))
        )
        return DataResponse(
            data=PriceListItemResponse.model_validate(result), meta=meta
        )

    def update_item(
        self,
        id: int,
        item_id: int,
        body: PriceListItemUpdateRequest,
        handler: Injected[UpdatePriceListItemCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[PriceListItemResponse]:
        """Changes the price or the minimum quantity of a list's price."""
        result = handler.handle(
            UpdatePriceListItemCommand(price_list_id=id, item_id=item_id, **dict(body))
        )
        return DataResponse(
            data=PriceListItemResponse.model_validate(result), meta=meta
        )

    def delete_item(
        self,
        id: int,
        item_id: int,
        handler: Injected[DeletePriceListItemCommandHandler],
    ) -> None:
        handler.handle(DeletePriceListItemCommand(price_list_id=id, item_id=item_id))


class POSPriceRouter:
    """Precio de las líneas del carrito (S5.3) en /api/pos/prices"""

    def __init__(self):
        self.router = APIRouter()
        self.router.post(
            "/resolve",
            response_model=ListResponse[ResolvedPriceResponse],
            summary="Resolve the price of cart lines",
            responses=RESPONSES_QUERY,
            dependencies=[Depends(require_permission(Permission.POS_OPERATE))],
        )(self.resolve)

    def resolve(
        self,
        body: ResolvePricesRequest,
        handler: Injected[ResolvePricesQueryHandler],
        branch_id: int = Depends(require_branch),
        meta: Meta = Depends(get_meta),
    ) -> ListResponse[ResolvedPriceResponse]:
        """The price each line takes in a sale of that customer at the branch in
        `X-Branch-Id`: the customer's list, the branch's, then the general one
        (its quantity tiers over the product's price). A sale sold at another
        price needs a reason. A read: no `Idempotency-Key`."""
        result = handler.handle(
            ResolvePricesQuery(
                branch_id=branch_id,
                customer_id=body.customer_id,
                items=[
                    PriceLineInput(
                        product_id=item.product_id,
                        quantity=item.quantity,
                        presentation_id=item.presentation_id,
                    )
                    for item in body.items
                ],
            )
        )
        return ListResponse(
            data=[ResolvedPriceResponse.model_validate(r) for r in result], meta=meta
        )
