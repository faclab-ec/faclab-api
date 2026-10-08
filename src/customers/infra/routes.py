from fastapi import APIRouter, Depends, Query
from wireup import Injected

from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import require_permission
from src.customers.app.commands.customer import (
    ActivateCustomerCommand,
    ActivateCustomerCommandHandler,
    CreateCustomerCommand,
    CreateCustomerCommandHandler,
    DeactivateCustomerCommand,
    DeactivateCustomerCommandHandler,
    DeleteCustomerCommand,
    DeleteCustomerCommandHandler,
    UpdateCustomerCommand,
    UpdateCustomerCommandHandler,
)
from src.customers.app.commands.customer_contact import (
    CreateCustomerContactCommand,
    CreateCustomerContactCommandHandler,
    DeleteCustomerContactCommand,
    DeleteCustomerContactCommandHandler,
    UpdateCustomerContactCommand,
    UpdateCustomerContactCommandHandler,
)
from src.customers.app.queries.customer import (
    GetAllCustomersQuery,
    GetAllCustomersQueryHandler,
    GetCustomerByIdQuery,
    GetCustomerByIdQueryHandler,
    GetCustomerByTaxIdQuery,
    GetCustomerByTaxIdQueryHandler,
)
from src.customers.app.queries.customer_contact import (
    GetContactsByCustomerIdQuery,
    GetContactsByCustomerIdQueryHandler,
    GetCustomerContactByIdQuery,
    GetCustomerContactByIdQueryHandler,
)
from src.customers.infra.validators import (
    CustomerContactRequest,
    CustomerContactResponse,
    CustomerQueryParams,
    CustomerRequest,
    CustomerResponse,
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


class CustomerRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        """Sets up all the routes for the router."""
        _read = [Depends(require_permission(Permission.CUSTOMER_READ))]
        _write = [Depends(require_permission(Permission.CUSTOMER_WRITE))]

        self.router.post(
            "",
            response_model=DataResponse[CustomerResponse],
            summary="Create customer",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.create)
        self.router.put(
            "/{id}",
            response_model=DataResponse[CustomerResponse],
            summary="Update customer",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.update)
        self.router.delete(
            "/{id}",
            summary="Delete customer",
            responses=RESPONSES_DELETE,
            dependencies=_write,
        )(self.delete)
        self.router.get(
            "",
            response_model=PaginatedDataResponse[CustomerResponse],
            summary="Get all customers",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_all)
        self.router.get(
            "/{id}",
            response_model=DataResponse[CustomerResponse],
            summary="Get customer by ID",
            responses=RESPONSES_QUERY,
            dependencies=_read,
        )(self.get_by_id)
        self.router.get(
            "/search/by-tax-id",
            response_model=DataResponse[CustomerResponse],
            summary="Get customer by tax ID",
            responses=RESPONSES_QUERY,
            dependencies=_read,
        )(self.get_by_tax_id)
        self.router.post(
            "/{id}/activate",
            response_model=DataResponse[CustomerResponse],
            summary="Activate customer",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.activate)
        self.router.post(
            "/{id}/deactivate",
            response_model=DataResponse[CustomerResponse],
            summary="Deactivate customer",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.deactivate)
        self.router.post(
            "/{customer_id}/contacts",
            response_model=DataResponse[CustomerContactResponse],
            summary="Create customer contact",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.create_contact)
        self.router.get(
            "/{customer_id}/contacts",
            response_model=ListResponse[CustomerContactResponse],
            summary="Get customer contacts",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_customer_contacts)

    def create(
        self,
        handler: Injected[CreateCustomerCommandHandler],
        new_customer: CustomerRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CustomerResponse]:
        """Creates a new customer."""
        result = handler.handle(
            CreateCustomerCommand(**new_customer.model_dump(exclude_none=True))
        )
        return DataResponse(data=CustomerResponse.model_validate(result), meta=meta)

    def update(
        self,
        handler: Injected[UpdateCustomerCommandHandler],
        id: int,
        customer: CustomerRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CustomerResponse]:
        """Updates a customer."""
        result = handler.handle(
            UpdateCustomerCommand(id=id, **customer.model_dump(exclude_none=True))
        )
        return DataResponse(data=CustomerResponse.model_validate(result), meta=meta)

    def delete(
        self,
        handler: Injected[DeleteCustomerCommandHandler],
        id: int,
    ) -> None:
        """Deletes a customer."""
        handler.handle(DeleteCustomerCommand(id=id))

    def get_all(
        self,
        handler: Injected[GetAllCustomersQueryHandler],
        query_params: CustomerQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[CustomerResponse]:
        """Retrieves all customers."""
        result = handler.handle(
            GetAllCustomersQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[CustomerResponse.model_validate(c) for c in result["items"]],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )

    def get_by_id(
        self,
        handler: Injected[GetCustomerByIdQueryHandler],
        id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CustomerResponse]:
        """Retrieves a specific customer by its ID."""
        result = handler.handle(GetCustomerByIdQuery(id=id))
        return DataResponse(data=CustomerResponse.model_validate(result), meta=meta)

    def get_by_tax_id(
        self,
        handler: Injected[GetCustomerByTaxIdQueryHandler],
        tax_id: str = Query(..., alias="taxId", description="Tax ID to search for"),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CustomerResponse]:
        """Retrieves a customer by tax ID."""
        result = handler.handle(GetCustomerByTaxIdQuery(tax_id=tax_id))
        return DataResponse(data=CustomerResponse.model_validate(result), meta=meta)

    def activate(
        self,
        handler: Injected[ActivateCustomerCommandHandler],
        id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CustomerResponse]:
        """Activates a customer."""
        result = handler.handle(ActivateCustomerCommand(id=id))
        return DataResponse(data=CustomerResponse.model_validate(result), meta=meta)

    def deactivate(
        self,
        handler: Injected[DeactivateCustomerCommandHandler],
        id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CustomerResponse]:
        """Deactivates a customer."""
        result = handler.handle(DeactivateCustomerCommand(id=id))
        return DataResponse(data=CustomerResponse.model_validate(result), meta=meta)

    def create_contact(
        self,
        handler: Injected[CreateCustomerContactCommandHandler],
        customer_id: int,
        new_contact: CustomerContactRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CustomerContactResponse]:
        """Creates a new contact for a customer."""
        result = handler.handle(
            CreateCustomerContactCommand(
                customer_id=customer_id, **new_contact.model_dump(exclude_none=True)
            )
        )
        return DataResponse(
            data=CustomerContactResponse.model_validate(result), meta=meta
        )

    def get_customer_contacts(
        self,
        handler: Injected[GetContactsByCustomerIdQueryHandler],
        customer_id: int,
        meta: Meta = Depends(get_meta),
    ) -> ListResponse[CustomerContactResponse]:
        """Retrieves all contacts for a customer."""
        result = handler.handle(GetContactsByCustomerIdQuery(customer_id=customer_id))
        return ListResponse(
            data=[CustomerContactResponse.model_validate(c) for c in result],
            meta=meta,
        )


class CustomerContactRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        """Sets up all the routes for the router."""
        _read = [Depends(require_permission(Permission.CUSTOMER_READ))]
        _write = [Depends(require_permission(Permission.CUSTOMER_WRITE))]

        self.router.put(
            "/{id}",
            response_model=DataResponse[CustomerContactResponse],
            summary="Update customer contact",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.update)
        self.router.delete(
            "/{id}",
            summary="Delete customer contact",
            responses=RESPONSES_DELETE,
            dependencies=_write,
        )(self.delete)
        self.router.get(
            "/{id}",
            response_model=DataResponse[CustomerContactResponse],
            summary="Get customer contact by ID",
            responses=RESPONSES_QUERY,
            dependencies=_read,
        )(self.get_by_id)

    def update(
        self,
        handler: Injected[UpdateCustomerContactCommandHandler],
        id: int,
        contact: CustomerContactRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CustomerContactResponse]:
        """Updates a customer contact."""
        result = handler.handle(
            UpdateCustomerContactCommand(id=id, **contact.model_dump(exclude_none=True))
        )
        return DataResponse(
            data=CustomerContactResponse.model_validate(result), meta=meta
        )

    def delete(
        self,
        handler: Injected[DeleteCustomerContactCommandHandler],
        id: int,
    ) -> None:
        """Deletes a customer contact."""
        handler.handle(DeleteCustomerContactCommand(id=id))

    def get_by_id(
        self,
        handler: Injected[GetCustomerContactByIdQueryHandler],
        id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CustomerContactResponse]:
        """Retrieves a specific customer contact by its ID."""
        result = handler.handle(GetCustomerContactByIdQuery(id=id))
        return DataResponse(
            data=CustomerContactResponse.model_validate(result), meta=meta
        )
