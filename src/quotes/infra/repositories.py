from collections.abc import Sequence

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session
from wireup import injectable

from src.customers.infra.models import CustomerModel
from src.quotes.app.repositories import (
    QuoteFilter,
    QuoteItemRepository,
    QuoteRepository,
)
from src.quotes.domain.entities import OPEN_QUOTE_STATUSES, Quote, QuoteItem
from src.quotes.infra.mappers import QuoteItemMapper, QuoteMapper
from src.quotes.infra.models import QuoteItemModel, QuoteModel
from src.shared.infra.repositories import SqlAlchemyRepository
from src.shared.infra.tenant import tenant_criteria


@injectable(lifetime="scoped", as_type=QuoteRepository)
class SqlAlchemyQuoteRepository(SqlAlchemyRepository[Quote], QuoteRepository):
    __model__ = QuoteModel

    def __init__(self, session: Session, mapper: QuoteMapper):
        super().__init__(session, mapper)

    def page(self, where: QuoteFilter, limit: int | None, offset: int | None) -> dict:
        query = self._query()
        if where.status is not None:
            query = query.filter(QuoteModel.status == where.status.value)
        if where.customer_id is not None:
            query = query.filter(QuoteModel.customer_id == where.customer_id)
        if where.branch_ids is not None:
            query = query.filter(QuoteModel.branch_id.in_(where.branch_ids))
        if where.number:
            query = query.filter(QuoteModel.number.ilike(f"%{where.number}%"))
        if where.in_force_on is not None:
            query = query.filter(
                QuoteModel.status.in_([s.value for s in OPEN_QUOTE_STATUSES]),
                QuoteModel.valid_until >= where.in_force_on,
            )
        if where.search:
            # The number or the customer's name or tax ID
            pattern = f"%{where.search}%"
            # In the join's condition: a quote to the final consumer has none
            query = query.outerjoin(
                CustomerModel,
                and_(
                    CustomerModel.id == QuoteModel.customer_id,
                    *tenant_criteria(CustomerModel),
                ),
            ).filter(
                or_(
                    QuoteModel.number.ilike(pattern),
                    CustomerModel.name.ilike(pattern),
                    CustomerModel.tax_id.ilike(pattern),
                )
            )
        total = query.with_entities(func.count(QuoteModel.id)).scalar()
        models = query.order_by(QuoteModel.id.desc()).limit(limit).offset(offset).all()
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [self.mapper.to_entity(model) for model in models],
        }


@injectable(lifetime="scoped", as_type=QuoteItemRepository)
class SqlAlchemyQuoteItemRepository(
    SqlAlchemyRepository[QuoteItem], QuoteItemRepository
):
    __model__ = QuoteItemModel

    def __init__(self, session: Session, mapper: QuoteItemMapper):
        super().__init__(session, mapper)

    def for_quote(self, quote_id: int) -> list[QuoteItem]:
        return self.filter(
            criteria=[QuoteItemModel.quote_id == quote_id], order_by="id"
        )

    def for_quotes(self, quote_ids: Sequence[int]) -> list[QuoteItem]:
        if not quote_ids:
            return []
        return self.filter(
            criteria=[QuoteItemModel.quote_id.in_(set(quote_ids))], order_by="id"
        )
