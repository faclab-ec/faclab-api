from sqlalchemy.orm import Session
from wireup import injectable

from src.catalog.product.app.repositories import CategoryRepository, ProductRepository
from src.catalog.product.domain.entities import Category, Product
from src.catalog.product.domain.exceptions import (
    ProductBarcodeAlreadyExistsError,
    ProductSkuAlreadyExistsError,
)
from src.catalog.product.infra.mappers import CategoryMapper, ProductMapper
from src.catalog.product.infra.models import CategoryModel, ProductModel
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
        "uq_products_tenant_barcode": ProductBarcodeAlreadyExistsError,
    }

    def __init__(self, session: Session, mapper: ProductMapper):
        super().__init__(session, mapper)
