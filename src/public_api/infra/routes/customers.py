from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from wireup import Injected

from src.auth.domain.scopes import Scope
from src.public_api.app.commands.catalog import (
    SaveApiCustomerCommand,
    SaveApiCustomerCommandHandler,
)
from src.public_api.app.queries.customers import (
    GetApiCustomerQuery,
    GetApiCustomerQueryHandler,
    ListApiCustomersQuery,
    ListApiCustomersQueryHandler,
)
from src.public_api.infra.dependencies import guarded
from src.public_api.infra.routes.common import READ, READ_ONE, WRITE, paginated
from src.public_api.infra.schemas.customers import (
    Customer,
    CustomerInput,
    CustomerListParams,
    IdentificationType,
)
from src.shared.infra.dependencies import get_meta
from src.shared.infra.idempotency.requests import (
    Idempotency,
    IdempotentRequest,
    idempotent_request,
)
from src.shared.infra.validators import DataResponse, Meta, PaginatedDataResponse


def customer_view(customer: dict) -> Customer:
    return Customer.model_validate(
        {
            **customer,
            "identification_type": IdentificationType.of(customer["tax_type"]),
            "identification": customer["tax_id"],
        }
    )


def _command(body: CustomerInput, customer_id: int | None = None):
    fields = body.model_dump(
        by_alias=False, exclude={"identification", "identification_type"}
    )
    return SaveApiCustomerCommand(
        **fields,
        tax_id=body.identification,
        tax_type=int(body.identification_type.tax_type),
        customer_id=customer_id,
    )


class ApiCustomerRouter:
    """`/api/v1/customers`"""

    def __init__(self):
        self.router = APIRouter()
        self.router.get(
            "",
            response_model=PaginatedDataResponse[Customer],
            summary="List customers",
            responses=READ,
            **guarded(Scope.CUSTOMERS_READ),
        )(self.list)
        self.router.get(
            "/{customer_id}",
            response_model=DataResponse[Customer],
            summary="Get a customer",
            responses=READ_ONE,
            **guarded(Scope.CUSTOMERS_READ),
        )(self.get)
        self.router.post(
            "",
            response_model=DataResponse[Customer],
            status_code=201,
            summary="Create a customer",
            responses=WRITE,
            **guarded(Scope.CUSTOMERS_WRITE),
        )(self.create)
        self.router.put(
            "/{customer_id}",
            response_model=DataResponse[Customer],
            summary="Replace a customer's editable fields",
            responses=WRITE,
            **guarded(Scope.CUSTOMERS_WRITE),
        )(self.update)

    def list(
        self,
        handler: Injected[ListApiCustomersQueryHandler],
        params: Annotated[CustomerListParams, Query()],
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[Customer]:
        """Customers; `identification` finds one by its RUC, cédula or
        passport. `sort`: `id`, `name`, `createdAt`, `updatedAt`."""
        page = handler.handle(
            ListApiCustomersQuery(
                page=params.page(), identification=params.identification
            )
        )
        return PaginatedDataResponse(
            data=[customer_view(item) for item in page.items],
            meta=paginated(page, meta),
        )

    def get(
        self,
        customer_id: int,
        handler: Injected[GetApiCustomerQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[Customer]:
        """A customer."""
        result = handler.handle(GetApiCustomerQuery(customer_id=customer_id))
        return DataResponse(data=customer_view(result), meta=meta)

    def create(
        self,
        body: CustomerInput,
        handler: Injected[SaveApiCustomerCommandHandler],
        reader: Injected[GetApiCustomerQueryHandler],
        idempotency: Injected[Idempotency],
        idempotent: IdempotentRequest | None = Depends(idempotent_request),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[Customer] | JSONResponse:
        """Create a customer. A RUC or cédula is validated. If a customer with
        that identification exists: `CUSTOMER_ALREADY_EXISTS` (409) with its id
        in `existingId`. Requires `Idempotency-Key`."""

        def respond() -> DataResponse[Customer]:
            created = handler.handle(_command(body))
            result = reader.handle(GetApiCustomerQuery(customer_id=created["id"]))
            return DataResponse(data=customer_view(result), meta=meta)

        return idempotency.run(idempotent, respond)

    def update(
        self,
        customer_id: int,
        body: CustomerInput,
        handler: Injected[SaveApiCustomerCommandHandler],
        reader: Injected[GetApiCustomerQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[Customer]:
        """Replace every editable field of the customer. Its credit, outside
        the public API, stays as it is."""
        handler.handle(_command(body, customer_id))
        result = reader.handle(GetApiCustomerQuery(customer_id=customer_id))
        return DataResponse(data=customer_view(result), meta=meta)
