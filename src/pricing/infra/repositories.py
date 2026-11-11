from collections.abc import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session
from wireup import injectable

from src.pricing.app.repositories import PriceListItemRepository, PriceListRepository
from src.pricing.domain.entities import PriceList, PriceListItem
from src.pricing.domain.exceptions import (
    PriceListItemAlreadyExistsError,
    PriceListNameAlreadyExistsError,
)
from src.pricing.infra.mappers import PriceListItemMapper, PriceListMapper
from src.pricing.infra.models import PriceListItemModel, PriceListModel
from src.shared.infra.repositories import SqlAlchemyRepository


@injectable(lifetime="scoped", as_type=PriceListRepository)
class SqlAlchemyPriceListRepository(
    SqlAlchemyRepository[PriceList], PriceListRepository
):
    __model__ = PriceListModel
    __unique_errors__ = {
        "uq_price_lists_tenant_name": PriceListNameAlreadyExistsError,
    }

    def __init__(self, session: Session, mapper: PriceListMapper):
        super().__init__(session, mapper)

    def default(self) -> PriceList | None:
        return self.first(is_default=True)

    def page(
        self, is_active: bool | None, limit: int | None, offset: int | None
    ) -> dict:
        query = self._query()
        if is_active is not None:
            query = query.filter(PriceListModel.is_active == is_active)
        total = query.with_entities(func.count(PriceListModel.id)).scalar()
        models = (
            query.order_by(
                PriceListModel.is_default.desc(), PriceListModel.name, PriceListModel.id
            )
            .limit(limit)
            .offset(offset)
            .all()
        )
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [self.mapper.to_entity(model).dict() for model in models],
        }


@injectable(lifetime="scoped", as_type=PriceListItemRepository)
class SqlAlchemyPriceListItemRepository(
    SqlAlchemyRepository[PriceListItem], PriceListItemRepository
):
    __model__ = PriceListItemModel
    __unique_errors__ = {
        "uq_price_list_items_tenant_list_presentation_min": (
            PriceListItemAlreadyExistsError
        ),
    }

    def __init__(self, session: Session, mapper: PriceListItemMapper):
        super().__init__(session, mapper)

    def for_products(
        self, price_list_ids: Iterable[int], product_ids: Iterable[int]
    ) -> list[PriceListItem]:
        lists, products = set(price_list_ids), set(product_ids)
        if not lists or not products:
            return []
        models = (
            self._query()
            .filter(
                PriceListItemModel.price_list_id.in_(lists),
                PriceListItemModel.product_id.in_(products),
            )
            .all()
        )
        return [self.mapper.to_entity(model) for model in models]

    def page(
        self,
        price_list_id: int,
        product_id: int | None,
        limit: int | None,
        offset: int | None,
    ) -> dict:
        query = self._query().filter(PriceListItemModel.price_list_id == price_list_id)
        if product_id is not None:
            query = query.filter(PriceListItemModel.product_id == product_id)
        total = query.with_entities(func.count(PriceListItemModel.id)).scalar()
        models = (
            query.order_by(
                PriceListItemModel.product_id,
                PriceListItemModel.presentation_id,
                PriceListItemModel.min_quantity,
            )
            .limit(limit)
            .offset(offset)
            .all()
        )
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [self.mapper.to_entity(model) for model in models],
        }
