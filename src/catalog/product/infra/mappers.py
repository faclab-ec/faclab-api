from wireup import injectable

from src.catalog.product.domain.entities import Category, Product, ProductPresentation
from src.catalog.product.infra.models import (
    CategoryModel,
    ProductModel,
    ProductPresentationModel,
)
from src.shared.infra.mappers import Mapper


@injectable(lifetime="singleton")
class CategoryMapper(Mapper[Category, CategoryModel]):
    __entity__ = Category


@injectable(lifetime="singleton")
class ProductMapper(Mapper[Product, ProductModel]):
    __entity__ = Product
    __exclude_fields__ = frozenset({"created_at"})


@injectable(lifetime="singleton")
class ProductPresentationMapper(Mapper[ProductPresentation, ProductPresentationModel]):
    __entity__ = ProductPresentation
    __exclude_fields__ = frozenset({"created_at"})
