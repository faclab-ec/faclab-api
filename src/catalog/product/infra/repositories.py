from collections.abc import Iterable

from sqlalchemy.orm import Session
from wireup import injectable

from src.catalog.product.app.repositories import (
    CategoryRepository,
    ProductPresentationRepository,
    ProductRepository,
)
from src.catalog.product.domain.entities import Category, Product, ProductPresentation
from src.catalog.product.domain.exceptions import (
    ProductBarcodeAlreadyExistsError,
    ProductPresentationNameAlreadyExistsError,
    ProductSkuAlreadyExistsError,
)
from src.catalog.product.infra.mappers import (
    CategoryMapper,
    ProductMapper,
    ProductPresentationMapper,
)
from src.catalog.product.infra.models import (
    CategoryModel,
    ProductModel,
    ProductPresentationModel,
)
from src.shared.infra.repositories import SqlAlchemyRepository


@injectable(lifetime="scoped", as_type=CategoryRepository)
class SqlAlchemyCategoryRepository(SqlAlchemyRepository[Category], CategoryRepository):
    __model__ = CategoryModel

    def __init__(self, session: Session, mapper: CategoryMapper):
        super().__init__(session, mapper)


@injectable(lifetime="scoped", as_type=ProductRepository)
class SqlAlchemyProductRepository(SqlAlchemyRepository[Product], ProductRepository):
    __model__ = ProductModel
    __unique_errors__ = {
        "uq_products_tenant_sku": ProductSkuAlreadyExistsError,
    }

    def __init__(self, session: Session, mapper: ProductMapper):
        super().__init__(session, mapper)


@injectable(lifetime="scoped", as_type=ProductPresentationRepository)
class SqlAlchemyProductPresentationRepository(
    SqlAlchemyRepository[ProductPresentation], ProductPresentationRepository
):
    __model__ = ProductPresentationModel
    __unique_errors__ = {
        "uq_product_presentations_tenant_barcode": ProductBarcodeAlreadyExistsError,
        "uq_product_presentations_tenant_product_name": (
            ProductPresentationNameAlreadyExistsError
        ),
    }

    def __init__(self, session: Session, mapper: ProductPresentationMapper):
        super().__init__(session, mapper)

    def for_products(self, product_ids: Iterable[int]) -> list[ProductPresentation]:
        ids = set(product_ids)
        if not ids:
            return []
        models = (
            self._query()
            .filter(ProductPresentationModel.product_id.in_(ids))
            .order_by(
                ProductPresentationModel.product_id,
                ProductPresentationModel.is_base.desc(),
                ProductPresentationModel.factor,
                ProductPresentationModel.id,
            )
            .all()
        )
        return [self.mapper.to_entity(model) for model in models]

    def base_of(self, product_id: int) -> ProductPresentation | None:
        return self.first(product_id=product_id, is_base=True)

    def by_barcode(self, barcode: str) -> ProductPresentation | None:
        return self.first(barcode=barcode)
