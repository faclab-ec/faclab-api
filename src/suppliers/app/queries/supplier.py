from dataclasses import dataclass

from wireup import injectable

from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.specifications import Specification, all_of
from src.suppliers.app.repositories import SupplierRepository
from src.suppliers.domain.specifications import SupplierBySearchTerm, SuppliersByStatus


@dataclass
class GetAllSuppliersQuery(Query):
    is_active: bool | None = None
    search: str | None = None
    limit: int | None = None
    offset: int | None = None


@injectable(lifetime="scoped")
class GetAllSuppliersQueryHandler(QueryHandler[GetAllSuppliersQuery, dict]):
    def __init__(self, repo: SupplierRepository):
        self.repo = repo

    def _handle(self, query: GetAllSuppliersQuery) -> dict:
        specs: list[Specification] = []
        if query.is_active is not None:
            specs.append(SuppliersByStatus(query.is_active))
        if query.search:
            specs.append(SupplierBySearchTerm(query.search))
        return self.repo.paginate_by_spec(
            all_of(specs), limit=query.limit, offset=query.offset
        )


@dataclass
class GetSupplierByIdQuery(Query):
    id: int = 0


@injectable(lifetime="scoped")
class GetSupplierByIdQueryHandler(QueryHandler[GetSupplierByIdQuery, dict]):
    def __init__(self, repo: SupplierRepository):
        self.repo = repo

    def _handle(self, query: GetSupplierByIdQuery) -> dict:
        supplier = self.repo.get_by_id(query.id)
        if supplier is None:
            raise NotFoundError(f"Supplier with id {query.id} not found")
        return supplier.dict()
