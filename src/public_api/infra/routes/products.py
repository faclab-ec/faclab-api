from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from wireup import Injected

from src.auth.domain.scopes import Scope
from src.catalog.product.app.commands.create_product import (
    CreateProductCommand,
    CreateProductCommandHandler,
)
from src.public_api.app.commands.catalog import (
    UpdateApiProductCommand,
    UpdateApiProductCommandHandler,
)
from src.public_api.app.queries.products import (
    GetApiProductQuery,
    GetApiProductQueryHandler,
    ListApiProductsQuery,
    ListApiProductsQueryHandler,
)
from src.public_api.infra.dependencies import guarded
from src.public_api.infra.routes.common import READ, READ_ONE, WRITE, paginated
from src.public_api.infra.schemas.products import (
    Product,
    ProductInput,
    ProductListParams,
)
from src.shared.infra.dependencies import get_meta
from src.shared.infra.idempotency.requests import (
    Idempotency,
    IdempotentRequest,
    idempotent_request,
)
from src.shared.infra.validators import DataResponse, Meta, PaginatedDataResponse


def product_view(product: dict) -> Product:
    """A product as the public API shows it: each presentation with the price
    it is sold at"""
    return Product.model_validate(
        {
            **product,
            "presentations": [
                {**p, "sale_price": p["effective_sale_price"]}
                for p in product["presentations"]
            ],
        }
    )


class ApiProductRouter:
    """`/api/v1/products`"""

    def __init__(self):
        self.router = APIRouter()
        self.router.get(
            "",
            response_model=PaginatedDataResponse[Product],
            summary="List products",
            responses=READ,
            **guarded(Scope.PRODUCTS_READ),
        )(self.list)
        self.router.get(
            "/{product_id}",
            response_model=DataResponse[Product],
            summary="Get a product",
            responses=READ_ONE,
            **guarded(Scope.PRODUCTS_READ),
        )(self.get)
        self.router.post(
            "",
            response_model=DataResponse[Product],
            status_code=201,
            summary="Create a product",
            responses=WRITE,
            **guarded(Scope.PRODUCTS_WRITE),
        )(self.create)
        self.router.put(
            "/{product_id}",
            response_model=DataResponse[Product],
            summary="Replace a product's editable fields",
            responses=WRITE,
            **guarded(Scope.PRODUCTS_WRITE),
        )(self.update)

    def list(
        self,
        handler: Injected[ListApiProductsQueryHandler],
        params: Annotated[ProductListParams, Query()],
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[Product]:
        """Products with their unit and presentations. Sync the catalog with
        `updatedSince` (a change of a presentation updates its product). `sort`:
        `id`, `name`, `sku`, `createdAt`, `updatedAt`."""
        page = handler.handle(
            ListApiProductsQuery(
                page=params.page(),
                sku=params.sku,
                barcode=params.barcode,
                search=params.search,
            )
        )
        return PaginatedDataResponse(
            data=[product_view(item) for item in page.items],
            meta=paginated(page, meta),
        )

    def get(
        self,
        product_id: int,
        handler: Injected[GetApiProductQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[Product]:
        """A product with its presentations."""
        result = handler.handle(GetApiProductQuery(product_id=product_id))
        return DataResponse(data=product_view(result), meta=meta)

    def create(
        self,
        body: ProductInput,
        handler: Injected[CreateProductCommandHandler],
        reader: Injected[GetApiProductQueryHandler],
        idempotency: Injected[Idempotency],
        idempotent: IdempotentRequest | None = Depends(idempotent_request),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[Product] | JSONResponse:
        """Create a product with its base presentation (its unit, factor 1 and
        `barcode`). A SKU or barcode already taken: `PRODUCT_SKU_ALREADY_EXISTS`
        or `PRODUCT_BARCODE_ALREADY_EXISTS` (409); a construction material with
        another VAT than 5%: `CONSTRUCTION_MATERIAL_TAX_MISMATCH`. Requires
        `Idempotency-Key`."""

        def respond() -> DataResponse[Product]:
            created = handler.handle(
                CreateProductCommand(**body.model_dump(by_alias=False))
            )
            result = reader.handle(GetApiProductQuery(product_id=created["id"]))
            return DataResponse(data=product_view(result), meta=meta)

        return idempotency.run(idempotent, respond)

    def update(
        self,
        product_id: int,
        body: ProductInput,
        handler: Injected[UpdateApiProductCommandHandler],
        reader: Injected[GetApiProductQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[Product]:
        """Replace every editable field of the product (what the body leaves
        out takes its default). The cost and the stock thresholds, outside the
        public API, stay as they are."""
        handler.handle(
            UpdateApiProductCommand(
                product_id=product_id, **body.model_dump(by_alias=False)
            )
        )
        result = reader.handle(GetApiProductQuery(product_id=product_id))
        return DataResponse(data=product_view(result), meta=meta)
