from src.catalog.product.app.commands.create_category import (
    CreateCategoryCommandHandler,
)
from src.catalog.product.app.commands.create_product import CreateProductCommandHandler
from src.catalog.product.app.commands.delete_category import (
    DeleteCategoryCommandHandler,
)
from src.catalog.product.app.commands.delete_product import DeleteProductCommandHandler
from src.catalog.product.app.commands.presentations import (
    CreateProductPresentationCommandHandler,
    DeleteProductPresentationCommandHandler,
    UpdateProductPresentationCommandHandler,
)
from src.catalog.product.app.commands.update_category import (
    UpdateCategoryCommandHandler,
)
from src.catalog.product.app.commands.update_product import UpdateProductCommandHandler
from src.catalog.product.app.presentations import ProductPresentations
from src.catalog.product.app.quantities import ProductQuantities
from src.catalog.product.app.queries.get_categories import (
    GetAllCategoriesQueryHandler,
    GetCategoryByIdQueryHandler,
)
from src.catalog.product.app.queries.get_products import (
    GetAllProductsQueryHandler,
    GetProductByBarcodeQueryHandler,
    GetProductByIdQueryHandler,
    GetProductPresentationsQueryHandler,
    SearchProductsQueryHandler,
)
from src.catalog.product.infra.mappers import (
    CategoryMapper,
    ProductMapper,
    ProductPresentationMapper,
)
from src.catalog.product.infra.repositories import (
    SqlAlchemyCategoryRepository,
    SqlAlchemyProductPresentationRepository,
    SqlAlchemyProductRepository,
)

INJECTABLES = [
    ProductQuantities,
    ProductPresentations,
    CategoryMapper,
    ProductMapper,
    ProductPresentationMapper,
    SqlAlchemyCategoryRepository,
    SqlAlchemyProductRepository,
    SqlAlchemyProductPresentationRepository,
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
    GetProductByBarcodeQueryHandler,
    GetProductPresentationsQueryHandler,
    CreateProductPresentationCommandHandler,
    UpdateProductPresentationCommandHandler,
    DeleteProductPresentationCommandHandler,
]
