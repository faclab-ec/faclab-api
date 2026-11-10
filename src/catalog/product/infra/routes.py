from fastapi import APIRouter, Depends
from wireup import Injected

from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import require_permission
from src.catalog.product.app.commands.create_category import (
    CreateCategoryCommand,
    CreateCategoryCommandHandler,
)
from src.catalog.product.app.commands.create_product import (
    CreateProductCommand,
    CreateProductCommandHandler,
)
from src.catalog.product.app.commands.delete_category import (
    DeleteCategoryCommand,
    DeleteCategoryCommandHandler,
)
from src.catalog.product.app.commands.delete_product import (
    DeleteProductCommand,
    DeleteProductCommandHandler,
)
from src.catalog.product.app.commands.presentations import (
    CreateProductPresentationCommand,
    CreateProductPresentationCommandHandler,
    DeleteProductPresentationCommand,
    DeleteProductPresentationCommandHandler,
    UpdateProductPresentationCommand,
    UpdateProductPresentationCommandHandler,
)
from src.catalog.product.app.commands.update_category import (
    UpdateCategoryCommand,
    UpdateCategoryCommandHandler,
)
from src.catalog.product.app.commands.update_product import (
    UpdateProductCommand,
    UpdateProductCommandHandler,
)
from src.catalog.product.app.queries.get_categories import (
    GetAllCategoriesQuery,
    GetAllCategoriesQueryHandler,
    GetCategoryByIdQuery,
    GetCategoryByIdQueryHandler,
)
from src.catalog.product.app.queries.get_products import (
    GetAllProductsQuery,
    GetAllProductsQueryHandler,
    GetProductByIdQuery,
    GetProductByIdQueryHandler,
    GetProductPresentationsQuery,
    GetProductPresentationsQueryHandler,
)
from src.catalog.product.infra.validators import (
    CategoryQueryParams,
    CategoryRequest,
    CategoryResponse,
    ProductPresentationRequest,
    ProductPresentationResponse,
    ProductQueryParams,
    ProductRequest,
    ProductResponse,
)
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import (
    RESPONSES_COMMAND,
    RESPONSES_DELETE,
    RESPONSES_LIST,
    RESPONSES_QUERY,
    DataResponse,
    ListResponse,
    Meta,
    PaginatedDataResponse,
)


class CategoryRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        """Sets up all the routes for the router."""
        _read = [Depends(require_permission(Permission.PRODUCT_READ))]
        _write = [Depends(require_permission(Permission.CATEGORY_WRITE))]

        self.router.post(
            "",
            response_model=DataResponse[CategoryResponse],
            summary="Save category",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.create)
        self.router.put(
            "/{id}",
            response_model=DataResponse[CategoryResponse],
            summary="Update category",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.update)
        self.router.delete(
            "/{id}",
            summary="Delete category",
            responses=RESPONSES_DELETE,
            dependencies=_write,
        )(self.delete)
        self.router.get(
            "",
            response_model=PaginatedDataResponse[CategoryResponse],
            summary="Get all categories",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_all)
        self.router.get(
            "/{id}",
            response_model=DataResponse[CategoryResponse],
            summary="Get category by ID",
            responses=RESPONSES_QUERY,
            dependencies=_read,
        )(self.get_by_id)

    def create(
        self,
        new_category: CategoryRequest,
        handler: Injected[CreateCategoryCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CategoryResponse]:
        """Saves a category."""
        result = handler.handle(
            CreateCategoryCommand(**new_category.model_dump(exclude_none=True))
        )
        return DataResponse(data=CategoryResponse.model_validate(result), meta=meta)

    def update(
        self,
        id: int,
        category: CategoryRequest,
        handler: Injected[UpdateCategoryCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CategoryResponse]:
        """Updates a category."""
        result = handler.handle(
            UpdateCategoryCommand(
                category_id=id, **category.model_dump(exclude_none=True)
            )
        )
        return DataResponse(data=CategoryResponse.model_validate(result), meta=meta)

    def delete(self, id: int, handler: Injected[DeleteCategoryCommandHandler]) -> None:
        """Deletes a category."""
        handler.handle(DeleteCategoryCommand(category_id=id))

    def get_all(
        self,
        handler: Injected[GetAllCategoriesQueryHandler],
        query_params: CategoryQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[CategoryResponse]:
        """Retrieves all categories."""
        result = handler.handle(
            GetAllCategoriesQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[CategoryResponse.model_validate(c) for c in result["items"]],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )

    def get_by_id(
        self,
        id: int,
        handler: Injected[GetCategoryByIdQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CategoryResponse]:
        """Retrieves a specific category by its ID."""
        result = handler.handle(GetCategoryByIdQuery(category_id=id))
        return DataResponse(data=CategoryResponse.model_validate(result), meta=meta)


class ProductRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        """Sets up all the routes for the router."""
        _read = [Depends(require_permission(Permission.PRODUCT_READ))]
        _write = [Depends(require_permission(Permission.PRODUCT_WRITE))]

        self.router.post(
            "",
            response_model=DataResponse[ProductResponse],
            summary="Save product",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.create)
        self.router.put(
            "/{id}",
            response_model=DataResponse[ProductResponse],
            summary="Update product",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.update)
        self.router.delete(
            "/{id}",
            summary="Delete product",
            responses=RESPONSES_DELETE,
            dependencies=_write,
        )(self.delete)
        self.router.get(
            "",
            response_model=PaginatedDataResponse[ProductResponse],
            summary="Get all products",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_all)
        self.router.get(
            "/{id}",
            response_model=DataResponse[ProductResponse],
            summary="Get product by ID",
            responses=RESPONSES_QUERY,
            dependencies=_read,
        )(self.get_by_id)
        self.router.get(
            "/{id}/presentations",
            response_model=ListResponse[ProductPresentationResponse],
            summary="Get the presentations of a product",
            responses=RESPONSES_QUERY,
            dependencies=_read,
        )(self.get_presentations)
        self.router.post(
            "/{id}/presentations",
            response_model=DataResponse[ProductPresentationResponse],
            summary="Add a presentation to a product",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.create_presentation)
        self.router.put(
            "/{id}/presentations/{presentation_id}",
            response_model=DataResponse[ProductPresentationResponse],
            summary="Update a presentation of a product",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.update_presentation)
        self.router.delete(
            "/{id}/presentations/{presentation_id}",
            summary="Delete a presentation of a product",
            responses=RESPONSES_DELETE,
            dependencies=_write,
        )(self.delete_presentation)

    def create(
        self,
        new_product: ProductRequest,
        handler: Injected[CreateProductCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ProductResponse]:
        """Saves a product."""
        result = handler.handle(
            CreateProductCommand(**new_product.model_dump(exclude_none=True))
        )
        return DataResponse(data=ProductResponse.model_validate(result), meta=meta)

    def update(
        self,
        id: int,
        product: ProductRequest,
        handler: Injected[UpdateProductCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ProductResponse]:
        """Updates a product."""
        result = handler.handle(
            UpdateProductCommand(product_id=id, **product.model_dump(exclude_none=True))
        )
        return DataResponse(data=ProductResponse.model_validate(result), meta=meta)

    def delete(self, id: int, handler: Injected[DeleteProductCommandHandler]) -> None:
        """Deletes a product."""
        handler.handle(DeleteProductCommand(product_id=id))

    def get_all(
        self,
        handler: Injected[GetAllProductsQueryHandler],
        query_params: ProductQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[ProductResponse]:
        """Retrieves all products."""
        result = handler.handle(
            GetAllProductsQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[ProductResponse.model_validate(p) for p in result["items"]],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )

    def get_by_id(
        self,
        id: int,
        handler: Injected[GetProductByIdQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ProductResponse]:
        """Retrieves a specific product by its ID."""
        result = handler.handle(GetProductByIdQuery(product_id=id))
        return DataResponse(data=ProductResponse.model_validate(result), meta=meta)

    def get_presentations(
        self,
        id: int,
        handler: Injected[GetProductPresentationsQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> ListResponse[ProductPresentationResponse]:
        """The product's presentations: the base one (its unit of measure, with the
        product's barcode and prices) first, then by factor."""
        result = handler.handle(GetProductPresentationsQuery(product_id=id))
        return ListResponse(
            data=[ProductPresentationResponse.model_validate(p) for p in result],
            meta=meta,
        )

    def create_presentation(
        self,
        id: int,
        presentation: ProductPresentationRequest,
        handler: Injected[CreateProductPresentationCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ProductPresentationResponse]:
        """Adds a presentation (box of 100, roll of 50 m): its factor in base units,
        greater than zero, and optionally its own barcode, price and cost."""
        result = handler.handle(
            # dict() keeps the Decimals that model_dump() turns into floats
            CreateProductPresentationCommand(product_id=id, **dict(presentation))
        )
        return DataResponse(
            data=ProductPresentationResponse.model_validate(result), meta=meta
        )

    def update_presentation(
        self,
        id: int,
        presentation_id: int,
        presentation: ProductPresentationRequest,
        handler: Injected[UpdateProductPresentationCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ProductPresentationResponse]:
        """Replaces a presentation. Of the base one only the barcode changes
        (400 BASE_PRESENTATION_FIXED otherwise)."""
        result = handler.handle(
            UpdateProductPresentationCommand(
                product_id=id,
                presentation_id=presentation_id,
                **dict(presentation),
            )
        )
        return DataResponse(
            data=ProductPresentationResponse.model_validate(result), meta=meta
        )

    def delete_presentation(
        self,
        id: int,
        presentation_id: int,
        handler: Injected[DeleteProductPresentationCommandHandler],
    ) -> None:
        """Deletes a presentation no line uses (409 RECORD_IN_USE otherwise:
        deactivate it). The base one can't be deleted."""
        handler.handle(
            DeleteProductPresentationCommand(
                product_id=id, presentation_id=presentation_id
            )
        )
