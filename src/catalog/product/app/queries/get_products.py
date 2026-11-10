from dataclasses import dataclass

from wireup import injectable

from src.catalog.product.app.presentations import ProductPresentations
from src.catalog.product.app.quantities import ProductQuantities
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
    def __init__(
        self,
        repo: ProductRepository,
        quantities: ProductQuantities,
        presentations: ProductPresentations,
    ):
        self.repo = repo
        self.quantities = quantities
        self.presentations = presentations

    def _handle(self, query: GetAllProductsQuery) -> dict:
        specs: list[Specification] = []
        if query.category_id is not None:
            specs.append(ProductInCategory(query.category_id))
        if query.search:
            specs.append(ProductBySearchTerm(query.search))
        page = self.repo.paginate_by_spec(
            all_of(specs), limit=query.limit, offset=query.offset
        )
        return {
            **page,
            "items": self.presentations.describe(
                self.quantities.describe(page["items"])
            ),
        }


@dataclass
class GetProductByIdQuery(Query):
    product_id: int


@injectable(lifetime="scoped")
class GetProductByIdQueryHandler(QueryHandler[GetProductByIdQuery, dict]):
    def __init__(
        self,
        repo: ProductRepository,
        quantities: ProductQuantities,
        presentations: ProductPresentations,
    ):
        self.repo = repo
        self.quantities = quantities
        self.presentations = presentations

    def _handle(self, query: GetProductByIdQuery) -> dict:
        product = self.repo.get_by_id(query.product_id)
        if product is None:
            raise NotFoundError(f"Product with id {query.product_id} not found")
        [described] = self.presentations.describe(
            self.quantities.describe([product.dict()])
        )
        return described


@dataclass
class SearchProductsQuery(Query):
    search_term: str
    limit: int | None = 20


@injectable(lifetime="scoped")
class SearchProductsQueryHandler(QueryHandler[SearchProductsQuery, list[dict]]):
    def __init__(
        self,
        repo: ProductRepository,
        quantities: ProductQuantities,
        presentations: ProductPresentations,
    ):
        self.repo = repo
        self.quantities = quantities
        self.presentations = presentations

    def _handle(self, query: SearchProductsQuery) -> list[dict]:
        spec = ProductBySearchTerm(query.search_term)
        products = self.repo.filter_by_spec(spec, limit=query.limit)
        return self.presentations.describe(
            self.quantities.describe([p.dict() for p in products])
        )


@dataclass
class GetProductByBarcodeQuery(Query):
    barcode: str


@injectable(lifetime="scoped")
class GetProductByBarcodeQueryHandler(QueryHandler[GetProductByBarcodeQuery, dict]):
    """El producto y la presentación de un código de barras escaneado (S5.2):
    ambos activos"""

    def __init__(
        self, quantities: ProductQuantities, presentations: ProductPresentations
    ):
        self.quantities = quantities
        self.presentations = presentations

    def _handle(self, query: GetProductByBarcodeQuery) -> dict:
        found = self.presentations.by_barcode(query.barcode)
        if found is None:
            raise NotFoundError(f"No product with barcode {query.barcode}")
        product, presentation = found
        described = self.presentations.describe(
            self.quantities.describe([product.dict()])
        )[0]
        view = next(p for p in described["presentations"] if p["id"] == presentation.id)
        return {"product": described, "presentation": view}


@dataclass
class GetProductPresentationsQuery(Query):
    product_id: int


@injectable(lifetime="scoped")
class GetProductPresentationsQueryHandler(
    QueryHandler[GetProductPresentationsQuery, list[dict]]
):
    """Las presentaciones del producto: la base primero y luego por factor"""

    def __init__(
        self,
        repo: ProductRepository,
        quantities: ProductQuantities,
        presentations: ProductPresentations,
    ):
        self.repo = repo
        self.quantities = quantities
        self.presentations = presentations

    def _handle(self, query: GetProductPresentationsQuery) -> list[dict]:
        product = self.repo.get_by_id(query.product_id)
        if product is None:
            raise NotFoundError(f"Product with id {query.product_id} not found")
        [described] = self.presentations.describe(
            self.quantities.describe([product.dict()])
        )
        return described["presentations"]
