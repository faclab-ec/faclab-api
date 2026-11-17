from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session
from wireup import injectable

from src.customers.infra.models import CustomerModel
from src.public_api.app.listing import Page, PageRequest, columns_of, ordering, paginate
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError
from src.shared.infra.tenant import tenant_criteria

SORT_FIELDS = {
    "id": CustomerModel.id,
    "name": CustomerModel.name,
    "createdAt": CustomerModel.created_at,
    "updatedAt": CustomerModel.updated_at,
}


@dataclass
class ListApiCustomersQuery(Query):
    page: PageRequest = field(default_factory=PageRequest)
    identification: str | None = None


@injectable(lifetime="scoped")
class ListApiCustomersQueryHandler(QueryHandler[ListApiCustomersQuery, Page]):
    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: ListApiCustomersQuery) -> Page:
        statement = select(CustomerModel).where(*tenant_criteria(CustomerModel))
        if query.identification is not None:
            statement = statement.where(CustomerModel.tax_id == query.identification)
        if query.page.updated_since is not None:
            statement = statement.where(
                CustomerModel.updated_at >= query.page.updated_since
            )
        page = paginate(
            self.session,
            statement,
            ordering(query.page, SORT_FIELDS, CustomerModel.id),
            query.page,
        )
        return Page(
            items=[columns_of(model) for model in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )


@dataclass
class GetApiCustomerQuery(Query):
    customer_id: int


@injectable(lifetime="scoped")
class GetApiCustomerQueryHandler(QueryHandler[GetApiCustomerQuery, dict]):
    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetApiCustomerQuery) -> dict:
        model = self.session.scalar(
            select(CustomerModel).where(
                *tenant_criteria(CustomerModel),
                CustomerModel.id == query.customer_id,
            )
        )
        if model is None:
            raise NotFoundError(f"Customer with id {query.customer_id} not found")
        return columns_of(model)
