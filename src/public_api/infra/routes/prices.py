from typing import Annotated

from fastapi import APIRouter, Depends, Query
from wireup import Injected

from src.auth.domain.scopes import Scope
from src.public_api.app.queries.prices import (
    ListApiPriceListItemsQuery,
    ListApiPriceListItemsQueryHandler,
    ListApiPriceListsQuery,
    ListApiPriceListsQueryHandler,
)
from src.public_api.infra.dependencies import guarded
from src.public_api.infra.routes.common import READ, READ_ONE, paginated
from src.public_api.infra.schemas.base import ListParams
from src.public_api.infra.schemas.prices import (
    PriceList,
    PriceListItem,
    PriceListItemParams,
)
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import Meta, PaginatedDataResponse


class ApiPriceListRouter:
    """`/api/v1/price-lists`"""

    def __init__(self):
        self.router = APIRouter()
        self.router.get(
            "",
            response_model=PaginatedDataResponse[PriceList],
            summary="List price lists",
            responses=READ,
            **guarded(Scope.PRICES_READ),
        )(self.list)
        self.router.get(
            "/{price_list_id}/items",
            response_model=PaginatedDataResponse[PriceListItem],
            summary="List the prices of a list",
            responses=READ_ONE,
            **guarded(Scope.PRICES_READ),
        )(self.items)

    def list(
        self,
        handler: Injected[ListApiPriceListsQueryHandler],
        params: Annotated[ListParams, Query()],
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[PriceList]:
        """The price lists, the general one included. A sale is priced with
        the customer's list, else its branch's, else the general one; the first
        with a price wins. `sort`: `id`, `name`, `createdAt`."""
        page = handler.handle(ListApiPriceListsQuery(page=params.page()))
        return PaginatedDataResponse(
            data=[PriceList.model_validate(item) for item in page.items],
            meta=paginated(page, meta),
        )

    def items(
        self,
        price_list_id: int,
        handler: Injected[ListApiPriceListItemsQueryHandler],
        params: Annotated[PriceListItemParams, Query()],
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[PriceListItem]:
        """The prices of a list, per product, presentation and quantity tier:
        a line takes the item of its presentation with the highest
        `minQuantity` up to its quantity. `sort`: `id`, `productId`,
        `minQuantity`."""
        page = handler.handle(
            ListApiPriceListItemsQuery(
                price_list_id=price_list_id,
                page=params.page(),
                product_id=params.product_id,
            )
        )
        return PaginatedDataResponse(
            data=[PriceListItem.model_validate(item) for item in page.items],
            meta=paginated(page, meta),
        )
