from dataclasses import dataclass

from wireup import injectable

from src.catalog.product.app.repositories import ProductRepository
from src.catalog.product.domain.specifications import (
    ProductBySearchTerm,
    ProductInCategory,
)
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.specifications import Specification, all_of


@dataclass
class GetAllProductsQuery(Query):
    category_id: int | None = None
    search: str | None = None
    limit: int | None = None
    offset: int | None = None


@injectable(lifetime="scoped")
class GetAllProductsQueryHandler(QueryHandler[GetAllProductsQuery, dict]):
    def __init__(self, repo: ProductRepository):
        self.repo = repo

    def _handle(self, query: GetAllProductsQuery) -> dict:
        specs: list[Specification] = []
        if query.category_id is not None:
            specs.append(ProductInCategory(query.category_id))
        if query.search:
            specs.append(ProductBySearchTerm(query.search))
        return self.repo.paginate_by_spec(
            all_of(specs), limit=query.limit, offset=query.offset
        )


@dataclass
class GetProductByIdQuery(Query):
    product_id: int


@injectable(lifetime="scoped")
class GetProductByIdQueryHandler(QueryHandler[GetProductByIdQuery, dict]):
    def __init__(self, repo: ProductRepository):
        self.repo = repo

    def _handle(self, query: GetProductByIdQuery) -> dict:
        product = self.repo.get_by_id(query.product_id)
        if product is None:
            raise NotFoundError(f"Product with id {query.product_id} not found")
        return product.dict()


@dataclass
class SearchProductsQuery(Query):
    search_term: str
    limit: int | None = 20


@injectable(lifetime="scoped")
class SearchProductsQueryHandler(QueryHandler[SearchProductsQuery, list[dict]]):
    def __init__(self, repo: ProductRepository):
        self.repo = repo

    def _handle(self, query: SearchProductsQuery) -> list[dict]:
        spec = ProductBySearchTerm(query.search_term)
        products = self.repo.filter_by_spec(spec, limit=query.limit)
        return [p.dict() for p in products]
