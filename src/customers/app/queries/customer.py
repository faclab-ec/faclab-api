from dataclasses import dataclass

from wireup import injectable

from src.customers.app.repositories import CustomerRepository
from src.customers.domain.specifications import CustomerBySearchTerm
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class GetAllCustomersQuery(Query):
    search: str | None = None
    limit: int | None = None
    offset: int | None = None


@injectable(lifetime="scoped")
class GetAllCustomersQueryHandler(QueryHandler[GetAllCustomersQuery, dict]):
    def __init__(self, repo: CustomerRepository):
        self.repo = repo

    def _handle(self, query: GetAllCustomersQuery) -> dict:
        if query.search:
            return self.repo.paginate_by_spec(
                CustomerBySearchTerm(query.search),
                limit=query.limit,
                offset=query.offset,
            )
        return self.repo.paginate(limit=query.limit, offset=query.offset)


@dataclass
class GetCustomerByIdQuery(Query):
    id: int = 0


@injectable(lifetime="scoped")
class GetCustomerByIdQueryHandler(QueryHandler[GetCustomerByIdQuery, dict]):
    def __init__(self, repo: CustomerRepository):
        self.repo = repo

    def _handle(self, query: GetCustomerByIdQuery) -> dict:
        customer = self.repo.get_by_id(query.id)
        if customer is None:
            raise NotFoundError(f"Customer with id {query.id} not found")
        return customer.dict()


@dataclass
class GetCustomerByTaxIdQuery(Query):
    tax_id: str = ""


@injectable(lifetime="scoped")
class GetCustomerByTaxIdQueryHandler(QueryHandler[GetCustomerByTaxIdQuery, dict]):
    def __init__(self, repo: CustomerRepository):
        self.repo = repo

    def _handle(self, query: GetCustomerByTaxIdQuery) -> dict:
        customer = self.repo.first(tax_id=query.tax_id)
        if customer is None:
            raise NotFoundError(f"Customer with tax_id {query.tax_id} not found")
        return customer.dict()
