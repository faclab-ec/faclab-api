from fastapi import APIRouter, Depends
from wireup import Injected

from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import require_permission
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
from src.suppliers.app.commands.supplier import (
    ActivateSupplierCommand,
    ActivateSupplierCommandHandler,
    CreateSupplierCommand,
    CreateSupplierCommandHandler,
    DeactivateSupplierCommand,
    DeactivateSupplierCommandHandler,
    DeleteSupplierCommand,
    DeleteSupplierCommandHandler,
    UpdateSupplierCommand,
    UpdateSupplierCommandHandler,
)
from src.suppliers.app.commands.supplier_contact import (
    CreateSupplierContactCommand,
    CreateSupplierContactCommandHandler,
    DeleteSupplierContactCommand,
    DeleteSupplierContactCommandHandler,
    UpdateSupplierContactCommand,
    UpdateSupplierContactCommandHandler,
)
from src.suppliers.app.commands.supplier_product import (
    CreateSupplierProductCommand,
    CreateSupplierProductCommandHandler,
    DeleteSupplierProductCommand,
    DeleteSupplierProductCommandHandler,
    UpdateSupplierProductCommand,
    UpdateSupplierProductCommandHandler,
)
from src.suppliers.app.queries.supplier import (
    GetAllSuppliersQuery,
    GetAllSuppliersQueryHandler,
    GetSupplierByIdQuery,
    GetSupplierByIdQueryHandler,
)
from src.suppliers.app.queries.supplier_contact import (
    GetContactsBySupplierIdQuery,
    GetContactsBySupplierIdQueryHandler,
    GetSupplierContactByIdQuery,
    GetSupplierContactByIdQueryHandler,
)
from src.suppliers.app.queries.supplier_product import (
    GetProductSuppliersByProductIdQuery,
    GetProductSuppliersByProductIdQueryHandler,
    GetSupplierProductByIdQuery,
    GetSupplierProductByIdQueryHandler,
    GetSupplierProductsBySupplierIdQuery,
    GetSupplierProductsBySupplierIdQueryHandler,
)
from src.suppliers.infra.validators import (
    SupplierContactRequest,
    SupplierContactResponse,
    SupplierProductRequest,
    SupplierProductResponse,
    SupplierQueryParams,
    SupplierRequest,
    SupplierResponse,
)


class SupplierRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        """Sets up all the routes for the router."""
        _read = [Depends(require_permission(Permission.SUPPLIER_READ))]
        _write = [Depends(require_permission(Permission.SUPPLIER_WRITE))]

        self.router.post(
            "",
            response_model=DataResponse[SupplierResponse],
            summary="Create supplier",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.create)
        self.router.put(
            "/{id}",
            response_model=DataResponse[SupplierResponse],
            summary="Update supplier",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.update)
        self.router.delete(
            "/{id}",
            summary="Delete supplier",
            responses=RESPONSES_DELETE,
            dependencies=_write,
        )(self.delete)
        self.router.get(
            "",
            response_model=PaginatedDataResponse[SupplierResponse],
            summary="Get all suppliers",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_all)
        self.router.get(
            "/{id}",
            response_model=DataResponse[SupplierResponse],
            summary="Get supplier by ID",
            responses=RESPONSES_QUERY,
            dependencies=_read,
        )(self.get_by_id)
        self.router.post(
            "/{id}/activate",
            response_model=DataResponse[SupplierResponse],
            summary="Activate supplier",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.activate)
        self.router.post(
            "/{id}/deactivate",
            response_model=DataResponse[SupplierResponse],
            summary="Deactivate supplier",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.deactivate)
        self.router.post(
            "/{supplier_id}/contacts",
            response_model=DataResponse[SupplierContactResponse],
            summary="Create supplier contact",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.create_contact)
        self.router.get(
            "/{supplier_id}/contacts",
            response_model=ListResponse[SupplierContactResponse],
            summary="Get supplier contacts",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_supplier_contacts)
        self.router.post(
            "/{supplier_id}/products",
            response_model=DataResponse[SupplierProductResponse],
            summary="Add product to supplier catalog",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.create_supplier_product)
        self.router.get(
            "/{supplier_id}/products",
            response_model=ListResponse[SupplierProductResponse],
            summary="Get supplier products",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_supplier_products)

    def create(
        self,
        handler: Injected[CreateSupplierCommandHandler],
        new_supplier: SupplierRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SupplierResponse]:
        """Creates a new supplier."""
        result = handler.handle(
            CreateSupplierCommand(**new_supplier.model_dump(exclude_none=True))
        )
        return DataResponse(data=SupplierResponse.model_validate(result), meta=meta)

    def update(
        self,
        handler: Injected[UpdateSupplierCommandHandler],
        id: int,
        supplier: SupplierRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SupplierResponse]:
        """Updates a supplier."""
        result = handler.handle(
            UpdateSupplierCommand(id=id, **supplier.model_dump(exclude_none=True))
        )
        return DataResponse(data=SupplierResponse.model_validate(result), meta=meta)

    def delete(
        self,
        handler: Injected[DeleteSupplierCommandHandler],
        id: int,
    ) -> None:
        """Deletes a supplier."""
        handler.handle(DeleteSupplierCommand(id=id))

    def get_all(
        self,
        handler: Injected[GetAllSuppliersQueryHandler],
        query_params: SupplierQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[SupplierResponse]:
        """Retrieves all suppliers."""
        result = handler.handle(
            GetAllSuppliersQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[SupplierResponse.model_validate(s) for s in result["items"]],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )

    def get_by_id(
        self,
        handler: Injected[GetSupplierByIdQueryHandler],
        id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SupplierResponse]:
        """Retrieves a specific supplier by its ID."""
        result = handler.handle(GetSupplierByIdQuery(id=id))
        return DataResponse(data=SupplierResponse.model_validate(result), meta=meta)

    def activate(
        self,
        handler: Injected[ActivateSupplierCommandHandler],
        id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SupplierResponse]:
        """Activates a supplier."""
        result = handler.handle(ActivateSupplierCommand(id=id))
        return DataResponse(data=SupplierResponse.model_validate(result), meta=meta)

    def deactivate(
        self,
        handler: Injected[DeactivateSupplierCommandHandler],
        id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SupplierResponse]:
        """Deactivates a supplier."""
        result = handler.handle(DeactivateSupplierCommand(id=id))
        return DataResponse(data=SupplierResponse.model_validate(result), meta=meta)

    def create_contact(
        self,
        handler: Injected[CreateSupplierContactCommandHandler],
        supplier_id: int,
        new_contact: SupplierContactRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SupplierContactResponse]:
        """Creates a new contact for a supplier."""
        result = handler.handle(
            CreateSupplierContactCommand(
                supplier_id=supplier_id, **new_contact.model_dump(exclude_none=True)
            )
        )
        return DataResponse(
            data=SupplierContactResponse.model_validate(result), meta=meta
        )

    def get_supplier_contacts(
        self,
        handler: Injected[GetContactsBySupplierIdQueryHandler],
        supplier_id: int,
        meta: Meta = Depends(get_meta),
    ) -> ListResponse[SupplierContactResponse]:
        """Retrieves all contacts for a supplier."""
        result = handler.handle(GetContactsBySupplierIdQuery(supplier_id=supplier_id))
        return ListResponse(
            data=[SupplierContactResponse.model_validate(c) for c in result],
            meta=meta,
        )

    def create_supplier_product(
        self,
        handler: Injected[CreateSupplierProductCommandHandler],
        supplier_id: int,
        new_product: SupplierProductRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SupplierProductResponse]:
        """Adds a product to the supplier catalog."""
        result = handler.handle(
            CreateSupplierProductCommand(
                supplier_id=supplier_id,
                **new_product.model_dump(exclude_none=True),
            )
        )
        return DataResponse(
            data=SupplierProductResponse.model_validate(result), meta=meta
        )

    def get_supplier_products(
        self,
        handler: Injected[GetSupplierProductsBySupplierIdQueryHandler],
        supplier_id: int,
        meta: Meta = Depends(get_meta),
    ) -> ListResponse[SupplierProductResponse]:
        """Retrieves all products for a supplier."""
        result = handler.handle(
            GetSupplierProductsBySupplierIdQuery(supplier_id=supplier_id)
        )
        return ListResponse(
            data=[SupplierProductResponse.model_validate(p) for p in result],
            meta=meta,
        )


class SupplierContactRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        """Sets up all the routes for the router."""
        _read = [Depends(require_permission(Permission.SUPPLIER_READ))]
        _write = [Depends(require_permission(Permission.SUPPLIER_WRITE))]

        self.router.put(
            "/{id}",
            response_model=DataResponse[SupplierContactResponse],
            summary="Update supplier contact",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.update)
        self.router.delete(
            "/{id}",
            summary="Delete supplier contact",
            responses=RESPONSES_DELETE,
            dependencies=_write,
        )(self.delete)
        self.router.get(
            "/{id}",
            response_model=DataResponse[SupplierContactResponse],
            summary="Get supplier contact by ID",
            responses=RESPONSES_QUERY,
            dependencies=_read,
        )(self.get_by_id)

    def update(
        self,
        handler: Injected[UpdateSupplierContactCommandHandler],
        id: int,
        contact: SupplierContactRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SupplierContactResponse]:
        """Updates a supplier contact."""
        result = handler.handle(
            UpdateSupplierContactCommand(id=id, **contact.model_dump(exclude_none=True))
        )
        return DataResponse(
            data=SupplierContactResponse.model_validate(result), meta=meta
        )

    def delete(
        self,
        handler: Injected[DeleteSupplierContactCommandHandler],
        id: int,
    ) -> None:
        """Deletes a supplier contact."""
        handler.handle(DeleteSupplierContactCommand(id=id))

    def get_by_id(
        self,
        handler: Injected[GetSupplierContactByIdQueryHandler],
        id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SupplierContactResponse]:
        """Retrieves a specific supplier contact by its ID."""
        result = handler.handle(GetSupplierContactByIdQuery(id=id))
        return DataResponse(
            data=SupplierContactResponse.model_validate(result), meta=meta
        )


class SupplierProductRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        """Sets up all the routes for the router."""
        _read = [Depends(require_permission(Permission.SUPPLIER_READ))]
        _write = [Depends(require_permission(Permission.SUPPLIER_WRITE))]

        self.router.put(
            "/{id}",
            response_model=DataResponse[SupplierProductResponse],
            summary="Update supplier product",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.update)
        self.router.delete(
            "/{id}",
            summary="Delete supplier product",
            responses=RESPONSES_DELETE,
            dependencies=_write,
        )(self.delete)
        self.router.get(
            "/{id}",
            response_model=DataResponse[SupplierProductResponse],
            summary="Get supplier product by ID",
            responses=RESPONSES_QUERY,
            dependencies=_read,
        )(self.get_by_id)
        self.router.get(
            "/by-product/{product_id}",
            response_model=ListResponse[SupplierProductResponse],
            summary="Get all suppliers for a product",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_by_product)

    def update(
        self,
        handler: Injected[UpdateSupplierProductCommandHandler],
        id: int,
        product: SupplierProductRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SupplierProductResponse]:
        """Updates a supplier product."""
        result = handler.handle(
            UpdateSupplierProductCommand(id=id, **product.model_dump(exclude_none=True))
        )
        return DataResponse(
            data=SupplierProductResponse.model_validate(result), meta=meta
        )

    def delete(
        self,
        handler: Injected[DeleteSupplierProductCommandHandler],
        id: int,
    ) -> None:
        """Deletes a supplier product."""
        handler.handle(DeleteSupplierProductCommand(id=id))

    def get_by_id(
        self,
        handler: Injected[GetSupplierProductByIdQueryHandler],
        id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SupplierProductResponse]:
        """Retrieves a specific supplier product by its ID."""
        result = handler.handle(GetSupplierProductByIdQuery(id=id))
        return DataResponse(
            data=SupplierProductResponse.model_validate(result), meta=meta
        )

    def get_by_product(
        self,
        handler: Injected[GetProductSuppliersByProductIdQueryHandler],
        product_id: int,
        meta: Meta = Depends(get_meta),
    ) -> ListResponse[SupplierProductResponse]:
        """Retrieves all supplier entries for a given product."""
        result = handler.handle(
            GetProductSuppliersByProductIdQuery(product_id=product_id)
        )
        return ListResponse(
            data=[SupplierProductResponse.model_validate(p) for p in result],
            meta=meta,
        )
