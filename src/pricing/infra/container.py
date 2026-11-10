from src.pricing.app.commands.items import (
    CreatePriceListItemCommandHandler,
    DeletePriceListItemCommandHandler,
    UpdatePriceListItemCommandHandler,
)
from src.pricing.app.commands.price_lists import (
    CreatePriceListCommandHandler,
    DeletePriceListCommandHandler,
    UpdatePriceListCommandHandler,
)
from src.pricing.app.queries.price_lists import (
    GetPriceListItemsQueryHandler,
    GetPriceListQueryHandler,
    GetPriceListsQueryHandler,
)
from src.pricing.app.queries.resolve import ResolvePricesQueryHandler
from src.pricing.app.resolver import PriceResolver
from src.pricing.infra.mappers import PriceListItemMapper, PriceListMapper
from src.pricing.infra.repositories import (
    SqlAlchemyPriceListItemRepository,
    SqlAlchemyPriceListRepository,
)

INJECTABLES = [
    PriceListMapper,
    PriceListItemMapper,
    SqlAlchemyPriceListRepository,
    SqlAlchemyPriceListItemRepository,
    PriceResolver,
    CreatePriceListCommandHandler,
    UpdatePriceListCommandHandler,
    DeletePriceListCommandHandler,
    CreatePriceListItemCommandHandler,
    UpdatePriceListItemCommandHandler,
    DeletePriceListItemCommandHandler,
    GetPriceListsQueryHandler,
    GetPriceListQueryHandler,
    GetPriceListItemsQueryHandler,
    ResolvePricesQueryHandler,
]
