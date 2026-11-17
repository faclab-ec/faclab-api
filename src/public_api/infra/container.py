from src.public_api.app.commands.catalog import (
    SaveApiCustomerCommandHandler,
    UpdateApiProductCommandHandler,
)
from src.public_api.app.commands.sales import (
    CancelApiSaleCommandHandler,
    CreateApiSaleCommandHandler,
)
from src.public_api.app.queries.branches import ListApiBranchesQueryHandler
from src.public_api.app.queries.customers import (
    GetApiCustomerQueryHandler,
    ListApiCustomersQueryHandler,
)
from src.public_api.app.queries.prices import (
    ListApiPriceListItemsQueryHandler,
    ListApiPriceListsQueryHandler,
)
from src.public_api.app.queries.products import (
    GetApiProductQueryHandler,
    ListApiProductsQueryHandler,
)
from src.public_api.app.queries.sales import (
    GetApiSaleQueryHandler,
    ListApiSalesQueryHandler,
)
from src.public_api.app.queries.stock import ListApiStockQueryHandler

INJECTABLES = [
    ListApiBranchesQueryHandler,
    ListApiProductsQueryHandler,
    GetApiProductQueryHandler,
    UpdateApiProductCommandHandler,
    ListApiPriceListsQueryHandler,
    ListApiPriceListItemsQueryHandler,
    ListApiStockQueryHandler,
    ListApiCustomersQueryHandler,
    GetApiCustomerQueryHandler,
    SaveApiCustomerCommandHandler,
    CreateApiSaleCommandHandler,
    CancelApiSaleCommandHandler,
    ListApiSalesQueryHandler,
    GetApiSaleQueryHandler,
]
