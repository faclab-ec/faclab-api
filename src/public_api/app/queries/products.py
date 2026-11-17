from dataclasses import dataclass, field

from sqlalchemy import exists, select
from sqlalchemy.orm import Session
from wireup import injectable

from src.catalog.product.app.presentations import ProductPresentations
from src.catalog.product.app.quantities import ProductQuantities
from src.catalog.product.domain.specifications import ProductBySearchTerm
from src.catalog.product.infra.models import ProductModel, ProductPresentationModel
from src.public_api.app.listing import Page, PageRequest, columns_of, ordering, paginate
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError
from src.shared.infra.tenant import tenant_criteria

SORT_FIELDS = {
    "id": ProductModel.id,
    "name": ProductModel.name,
    "sku": ProductModel.sku,
    "createdAt": ProductModel.created_at,
    "updatedAt": ProductModel.updated_at,
}


@dataclass
class ListApiProductsQuery(Query):
    page: PageRequest = field(default_factory=PageRequest)
    sku: str | None = None
    # Of any presentation, active or not
    barcode: str | None = None
    search: str | None = None


@injectable(lifetime="scoped")
class ListApiProductsQueryHandler(QueryHandler[ListApiProductsQuery, Page]):
    """Products with their unit and presentations, for the catalog sync"""

    def __init__(
        self,
        session: Session,
        quantities: ProductQuantities,
        presentations: ProductPresentations,
    ):
        self.session = session
        self.quantities = quantities
        self.presentations = presentations

    def _handle(self, query: ListApiProductsQuery) -> Page:
        statement = select(ProductModel).where(*tenant_criteria(ProductModel))
        if query.sku is not None:
            statement = statement.where(ProductModel.sku == query.sku)
        if query.barcode is not None:
            statement = statement.where(
                exists().where(
                    ProductPresentationModel.product_id == ProductModel.id,
                    ProductPresentationModel.barcode == query.barcode,
                    *tenant_criteria(ProductPresentationModel),
                )
            )
        if query.search:
            statement = statement.where(
                *ProductBySearchTerm(query.search).to_query_criteria()
            )
        if query.page.updated_since is not None:
            statement = statement.where(
                ProductModel.updated_at >= query.page.updated_since
            )
        page = paginate(
            self.session,
            statement,
            ordering(query.page, SORT_FIELDS, ProductModel.id),
            query.page,
        )
        return Page(
            items=self._describe([columns_of(model) for model in page.items]),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    def _describe(self, products: list[dict]) -> list[dict]:
        return self.presentations.describe(self.quantities.describe(products))


@dataclass
class GetApiProductQuery(Query):
    product_id: int


@injectable(lifetime="scoped")
class GetApiProductQueryHandler(QueryHandler[GetApiProductQuery, dict]):
    def __init__(
        self,
        session: Session,
        quantities: ProductQuantities,
        presentations: ProductPresentations,
    ):
        self.session = session
        self.quantities = quantities
        self.presentations = presentations

    def _handle(self, query: GetApiProductQuery) -> dict:
        model = self.session.scalar(
            select(ProductModel).where(
                *tenant_criteria(ProductModel), ProductModel.id == query.product_id
            )
        )
        if model is None:
            raise NotFoundError(f"Product with id {query.product_id} not found")
        [described] = self.presentations.describe(
            self.quantities.describe([columns_of(model)])
        )
        return described
