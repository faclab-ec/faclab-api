from dataclasses import dataclass

from wireup import injectable

from src.catalog.product.app.repositories import (
    ProductPresentationRepository,
    ProductRepository,
)
from src.pricing.app.commands.price_lists import price_list_of
from src.pricing.app.repositories import PriceListItemRepository, PriceListRepository
from src.pricing.app.views import item_views
from src.shared.app.queries import Query, QueryHandler


@dataclass
class GetPriceListsQuery(Query):
    is_active: bool | None = None
    limit: int | None = None
    offset: int | None = None


@injectable(lifetime="scoped")
class GetPriceListsQueryHandler(QueryHandler[GetPriceListsQuery, dict]):
    """Las listas de la empresa: la general primero, luego por nombre"""

    def __init__(self, lists: PriceListRepository):
        self.lists = lists

    def _handle(self, query: GetPriceListsQuery) -> dict:
        return self.lists.page(query.is_active, query.limit, query.offset)


@dataclass
class GetPriceListQuery(Query):
    price_list_id: int


@injectable(lifetime="scoped")
class GetPriceListQueryHandler(QueryHandler[GetPriceListQuery, dict]):
    def __init__(self, lists: PriceListRepository):
        self.lists = lists

    def _handle(self, query: GetPriceListQuery) -> dict:
        return price_list_of(self.lists, query.price_list_id).dict()


@dataclass
class GetPriceListItemsQuery(Query):
    price_list_id: int
    product_id: int | None = None
    limit: int | None = None
    offset: int | None = None


@injectable(lifetime="scoped")
class GetPriceListItemsQueryHandler(QueryHandler[GetPriceListItemsQuery, dict]):
    """Los precios de una lista, con su producto y su presentación"""

    def __init__(
        self,
        lists: PriceListRepository,
        items: PriceListItemRepository,
        products: ProductRepository,
        presentations: ProductPresentationRepository,
    ):
        self.lists = lists
        self.items = items
        self.products = products
        self.presentations = presentations

    def _handle(self, query: GetPriceListItemsQuery) -> dict:
        price_list_of(self.lists, query.price_list_id)
        page = self.items.page(
            query.price_list_id, query.product_id, query.limit, query.offset
        )
        page["items"] = item_views(page["items"], self.products, self.presentations)
        return page
