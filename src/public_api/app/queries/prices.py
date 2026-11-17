from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session
from wireup import injectable

from src.pricing.infra.models import PriceListItemModel, PriceListModel
from src.public_api.app.listing import Page, PageRequest, columns_of, ordering, paginate
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError
from src.shared.infra.tenant import tenant_criteria

LIST_SORT_FIELDS = {
    "id": PriceListModel.id,
    "name": PriceListModel.name,
    "createdAt": PriceListModel.created_at,
}
ITEM_SORT_FIELDS = {
    "id": PriceListItemModel.id,
    "productId": PriceListItemModel.product_id,
    "minQuantity": PriceListItemModel.min_quantity,
}


@dataclass
class ListApiPriceListsQuery(Query):
    page: PageRequest = field(default_factory=PageRequest)


@injectable(lifetime="scoped")
class ListApiPriceListsQueryHandler(QueryHandler[ListApiPriceListsQuery, Page]):
    """The tenant's price lists, the general one included"""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: ListApiPriceListsQuery) -> Page:
        page = paginate(
            self.session,
            select(PriceListModel).where(*tenant_criteria(PriceListModel)),
            ordering(query.page, LIST_SORT_FIELDS, PriceListModel.id),
            query.page,
        )
        return Page(
            items=[columns_of(model) for model in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )


@dataclass
class ListApiPriceListItemsQuery(Query):
    price_list_id: int
    page: PageRequest = field(default_factory=PageRequest)
    product_id: int | None = None


@injectable(lifetime="scoped")
class ListApiPriceListItemsQueryHandler(QueryHandler[ListApiPriceListItemsQuery, Page]):
    """The prices of a list: by product, presentation and quantity tier"""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: ListApiPriceListItemsQuery) -> Page:
        exists = self.session.scalar(
            select(PriceListModel.id).where(
                *tenant_criteria(PriceListModel),
                PriceListModel.id == query.price_list_id,
            )
        )
        if exists is None:
            raise NotFoundError(f"Price list with id {query.price_list_id} not found")
        statement = select(PriceListItemModel).where(
            *tenant_criteria(PriceListItemModel),
            PriceListItemModel.price_list_id == query.price_list_id,
        )
        if query.product_id is not None:
            statement = statement.where(
                PriceListItemModel.product_id == query.product_id
            )
        page = paginate(
            self.session,
            statement,
            ordering(query.page, ITEM_SORT_FIELDS, PriceListItemModel.id),
            query.page,
        )
        return Page(
            items=[columns_of(model) for model in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )
