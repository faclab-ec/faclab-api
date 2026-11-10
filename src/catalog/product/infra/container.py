from src.catalog.product.app.commands.create_category import (
    CreateCategoryCommandHandler,
)
from src.catalog.product.app.commands.create_product import CreateProductCommandHandler
from src.catalog.product.app.commands.delete_category import (
    DeleteCategoryCommandHandler,
)
from src.catalog.product.app.commands.delete_product import DeleteProductCommandHandler
from src.catalog.product.app.commands.update_category import (
    UpdateCategoryCommandHandler,
)
from src.catalog.product.app.commands.update_product import UpdateProductCommandHandler
from src.catalog.product.app.quantities import ProductQuantities
from src.catalog.product.app.queries.get_categories import (
    GetAllCategoriesQueryHandler,
    GetCategoryByIdQueryHandler,
)
from src.catalog.product.app.queries.get_products import (
    GetAllProductsQueryHandler,
    GetProductByIdQueryHandler,
    SearchProductsQueryHandler,
)
from src.catalog.product.infra.mappers import CategoryMapper, ProductMapper
from src.catalog.product.infra.repositories import (
    SqlAlchemyCategoryRepository,
    SqlAlchemyProductRepository,
)

INJECTABLES = [
    ProductQuantities,
    CategoryMapper,
    ProductMapper,
    SqlAlchemyCategoryRepository,
    SqlAlchemyProductRepository,
    CreateCategoryCommandHandler,
    UpdateCategoryCommandHandler,
    DeleteCategoryCommandHandler,
    GetAllCategoriesQueryHandler,
    GetCategoryByIdQueryHandler,
    CreateProductCommandHandler,
    UpdateProductCommandHandler,
    DeleteProductCommandHandler,
    GetAllProductsQueryHandler,
    GetProductByIdQueryHandler,
    SearchProductsQueryHandler,
]
