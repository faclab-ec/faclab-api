from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from wireup import Injected

from src.auth.domain.principals import IntegrationPrincipal
from src.auth.domain.scopes import Scope
from src.auth.infra.dependencies import require_branch
from src.pos.infra.metrics import sale_attempt
from src.public_api.app.commands.sales import (
    CancelApiSaleCommand,
    CancelApiSaleCommandHandler,
    CreateApiSaleCommand,
    CreateApiSaleCommandHandler,
)
from src.public_api.app.queries.sales import (
    GetApiSaleQuery,
    GetApiSaleQueryHandler,
    ListApiSalesQuery,
    ListApiSalesQueryHandler,
)
from src.public_api.infra.dependencies import current_client, ensure_branch, guarded
from src.public_api.infra.routes.common import READ, READ_ONE, WRITE, paginated
from src.public_api.infra.schemas.sales import (
    CancelSaleInput,
    Sale,
    SaleInput,
    SaleListParams,
)
from src.public_api.infra.types import utc_naive
from src.shared.infra.dependencies import get_meta
from src.shared.infra.idempotency.requests import (
    Idempotency,
    IdempotentRequest,
    idempotent_request,
)
from src.shared.infra.validators import DataResponse, Meta, PaginatedDataResponse


def _create_command(
    body: SaleInput, client: IntegrationPrincipal, branch_id: int
) -> CreateApiSaleCommand:
    customer = body.customer
    return CreateApiSaleCommand(
        integration_client_id=client.client_id,
        branch_id=branch_id,
        emission_point_id=body.emission_point_id,
        location_id=body.location_id,
        items=[
            {
                "product_id": item.product_id,
                "presentation_id": item.presentation_id,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "override_reason": item.override_reason,
                "discount": item.discount_percent or 0,
            }
            for item in body.items
        ],
        payments=[
            {
                "payment_method": payment.method.value,
                "amount": payment.amount,
                "reference": payment.reference,
            }
            for payment in body.payments
        ],
        customer_id=customer.id if customer else None,
        identification=customer.identification if customer else None,
        external_reference=body.external_reference,
        notes=body.notes,
        created_by=client.display_name,
    )


class ApiSaleRouter:
    """`/api/v1/sales`"""

    def __init__(self):
        self.router = APIRouter()
        self.router.post(
            "",
            response_model=DataResponse[Sale],
            status_code=201,
            summary="Create and confirm a sale",
            responses=WRITE,
            **guarded(Scope.SALES_WRITE),
        )(self.create)
        self.router.get(
            "",
            response_model=PaginatedDataResponse[Sale],
            summary="List sales",
            responses=READ,
            **guarded(Scope.SALES_READ),
        )(self.list)
        self.router.get(
            "/{sale_id}",
            response_model=DataResponse[Sale],
            summary="Get a sale",
            responses=READ_ONE,
            **guarded(Scope.SALES_READ),
        )(self.get)
        self.router.post(
            "/{sale_id}/cancel",
            response_model=DataResponse[Sale],
            summary="Cancel a sale",
            responses=WRITE,
            **guarded(Scope.SALES_WRITE),
        )(self.cancel)

    def create(
        self,
        body: SaleInput,
        handler: Injected[CreateApiSaleCommandHandler],
        reader: Injected[GetApiSaleQueryHandler],
        idempotency: Injected[Idempotency],
        branch_id: int = Depends(require_branch),
        client: IntegrationPrincipal = Depends(current_client),
        idempotent: IdempotentRequest | None = Depends(idempotent_request),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[Sale] | JSONResponse:
        """Create a sale of channel `api` and confirm it in one step, in the
        branch of `X-Branch-Id`, at its emission point `emissionPointId` and
        taking the stock of its location `locationId` (see `GET /branches`).
        It is numbered in its branch and sent to be invoiced.

        Each line takes the price its lists give (the customer's, the branch's
        or the general one); another `unitPrice` needs `overrideReason`
        (`OVERRIDE_REASON_REQUIRED`) and is audited. The stock must cover it
        (`INSUFFICIENT_STOCK`). The sale arrives paid online: `CREDIT_CARD`,
        `DEBIT_CARD`, `TRANSFER` or `OTHER`, never cash nor credit,
        adding up to its total with VAT exactly (`INSUFFICIENT_PAYMENT`,
        `PAYMENT_EXCEEDS_BALANCE`). Without `customer`, it is sold to the final
        consumer. Requires `Idempotency-Key`: a retry with it gets the same
        sale, made once."""

        def respond() -> DataResponse[Sale]:
            with sale_attempt("api"):
                created = handler.handle(_create_command(body, client, branch_id))
            result = reader.handle(GetApiSaleQuery(sale_id=created["id"]))
            return DataResponse(data=Sale.model_validate(result), meta=meta)

        return idempotency.run(idempotent, respond)

    def list(
        self,
        handler: Injected[ListApiSalesQueryHandler],
        params: Annotated[SaleListParams, Query()],
        client: IntegrationPrincipal = Depends(current_client),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[Sale]:
        """The sales of the branches this client may operate in, of every
        channel, with their items, payments and invoice status. `from` and
        `to` filter by the moment they were sold. Sync them with
        `updatedSince`. `sort`: `id`, `saleDate`, `createdAt`, `updatedAt`."""
        if params.branch_id is not None:
            ensure_branch(client, params.branch_id)
        page = handler.handle(
            ListApiSalesQuery(
                page=params.page(),
                allowed_branch_ids=client.branch_ids,
                branch_id=params.branch_id,
                status=params.status,
                invoice_status=params.invoice_status,
                channel=params.channel,
                external_reference=params.external_reference,
                sold_from=utc_naive(params.from_) if params.from_ else None,
                sold_to=utc_naive(params.to) if params.to else None,
            )
        )
        return PaginatedDataResponse(
            data=[Sale.model_validate(item) for item in page.items],
            meta=paginated(page, meta),
        )

    def get(
        self,
        sale_id: int,
        handler: Injected[GetApiSaleQueryHandler],
        client: IntegrationPrincipal = Depends(current_client),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[Sale]:
        """A sale of a branch this client may operate in."""
        result = handler.handle(
            GetApiSaleQuery(sale_id=sale_id, allowed_branch_ids=client.branch_ids)
        )
        return DataResponse(data=Sale.model_validate(result), meta=meta)

    def cancel(
        self,
        sale_id: int,
        handler: Injected[CancelApiSaleCommandHandler],
        reader: Injected[GetApiSaleQueryHandler],
        idempotency: Injected[Idempotency],
        body: CancelSaleInput | None = None,
        client: IntegrationPrincipal = Depends(current_client),
        idempotent: IdempotentRequest | None = Depends(idempotent_request),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[Sale] | JSONResponse:
        """Cancel a sale this client created (`PERMISSION_DENIED` for any
        other): its stock goes back where it left from. Only before its invoice
        is on its way: while faclab-invoicing has it, `INVOICE_IN_PROGRESS`;
        once invoiced, it needs a credit note (`CREDIT_NOTE_REQUIRED`), which
        the public API doesn't issue yet. Requires `Idempotency-Key`."""

        def respond() -> DataResponse[Sale]:
            handler.handle(
                CancelApiSaleCommand(
                    integration_client_id=client.client_id,
                    sale_id=sale_id,
                    reason=body.reason if body else None,
                    allowed_branch_ids=client.branch_ids,
                )
            )
            result = reader.handle(
                GetApiSaleQuery(sale_id=sale_id, allowed_branch_ids=client.branch_ids)
            )
            return DataResponse(data=Sale.model_validate(result), meta=meta)

        return idempotency.run(idempotent, respond)
