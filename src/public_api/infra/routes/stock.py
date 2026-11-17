from typing import Annotated

from fastapi import APIRouter, Depends, Query
from wireup import Injected

from src.auth.domain.principals import IntegrationPrincipal
from src.auth.domain.scopes import Scope
from src.public_api.app.queries.stock import ListApiStockQuery, ListApiStockQueryHandler
from src.public_api.infra.dependencies import current_client, guarded, single_branch
from src.public_api.infra.routes.common import READ, paginated
from src.public_api.infra.schemas.stock import StockParams, StockRow
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import Meta, PaginatedDataResponse


class ApiStockRouter:
    """`/api/v1/stock`"""

    def __init__(self):
        self.router = APIRouter()
        self.router.get(
            "",
            response_model=PaginatedDataResponse[StockRow],
            summary="List the stock of a branch",
            responses=READ,
            **guarded(Scope.STOCK_READ),
        )(self.list)

    def list(
        self,
        handler: Injected[ListApiStockQueryHandler],
        params: Annotated[StockParams, Query()],
        client: IntegrationPrincipal = Depends(current_client),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[StockRow]:
        """The stock of a branch, one row per product and location of its
        warehouses, in base units. `branchId` is required unless the client
        may operate in a single branch (`BRANCH_REQUIRED`). Sync it with
        `updatedSince`. `sort`: `id`, `productId`, `updatedAt`."""
        page = handler.handle(
            ListApiStockQuery(
                branch_id=single_branch(client, params.branch_id),
                page=params.page(),
                product_id=params.product_id,
            )
        )
        return PaginatedDataResponse(
            data=[StockRow.model_validate(item) for item in page.items],
            meta=paginated(page, meta),
        )
