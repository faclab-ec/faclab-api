"""Admin routes for Sales (read-only, plus resending a sale to invoicing)"""

from fastapi import APIRouter, Depends
from wireup import Injected

from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import require_permission
from src.sales.app.commands.request_invoicing import (
    RequestSaleInvoicingCommand,
    RequestSaleInvoicingCommandHandler,
)
from src.sales.app.queries.get_payments import (
    GetSalePaymentsQuery,
    GetSalePaymentsQueryHandler,
)
from src.sales.app.queries.get_sale_items import (
    GetSaleItemsQuery,
    GetSaleItemsQueryHandler,
)
from src.sales.app.queries.get_sales import (
    GetAllSalesQuery,
    GetAllSalesQueryHandler,
    GetSaleByIdQuery,
    GetSaleByIdQueryHandler,
)
from src.sales.infra.validators import (
    PaymentResponse,
    SaleItemResponse,
    SaleQueryParams,
    SaleResponse,
)
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import (
    RESPONSES_COMMAND,
    RESPONSES_LIST,
    RESPONSES_QUERY,
    DataResponse,
    ListResponse,
    Meta,
    PaginatedDataResponse,
)


class SaleRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        _read = [Depends(require_permission(Permission.SALE_READ))]

        self.router.get(
            "",
            response_model=PaginatedDataResponse[SaleResponse],
            summary="List all sales",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_all_sales)
        self.router.get(
            "/{sale_id}",
            response_model=DataResponse[SaleResponse],
            summary="Get sale",
            responses=RESPONSES_QUERY,
            dependencies=_read,
        )(self.get_sale)
        self.router.get(
            "/{sale_id}/items",
            response_model=ListResponse[SaleItemResponse],
            summary="List sale items",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_sale_items)
        self.router.get(
            "/{sale_id}/payments",
            response_model=ListResponse[PaymentResponse],
            summary="List sale payments",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_sale_payments)
        self.router.post(
            "/{sale_id}/request-invoice",
            response_model=DataResponse[SaleResponse],
            status_code=202,
            summary="Send a sale to invoicing again",
            responses=RESPONSES_COMMAND,
            dependencies=[Depends(require_permission(Permission.SALE_WRITE))],
        )(self.request_invoice)

    def get_all_sales(
        self,
        handler: Injected[GetAllSalesQueryHandler],
        query_params: SaleQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[SaleResponse]:
        """List all sales with optional filtering by customer, status or invoice status. Supports pagination."""
        result = handler.handle(
            GetAllSalesQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[SaleResponse.model_validate(r) for r in result["items"]],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )

    def get_sale(
        self,
        handler: Injected[GetSaleByIdQueryHandler],
        sale_id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SaleResponse]:
        """Retrieve a sale by its ID, including current status, totals, and payment status."""
        result = handler.handle(GetSaleByIdQuery(sale_id=sale_id))
        return DataResponse(data=SaleResponse.model_validate(result), meta=meta)

    def get_sale_items(
        self,
        handler: Injected[GetSaleItemsQueryHandler],
        sale_id: int,
        meta: Meta = Depends(get_meta),
    ) -> ListResponse[SaleItemResponse]:
        """List all line items for a sale."""
        result = handler.handle(GetSaleItemsQuery(sale_id=sale_id))
        return ListResponse(
            data=[SaleItemResponse.model_validate(r) for r in result], meta=meta
        )

    def get_sale_payments(
        self,
        handler: Injected[GetSalePaymentsQueryHandler],
        sale_id: int,
        meta: Meta = Depends(get_meta),
    ) -> ListResponse[PaymentResponse]:
        """List all payments registered for a sale."""
        result = handler.handle(GetSalePaymentsQuery(sale_id=sale_id))
        return ListResponse(
            data=[PaymentResponse.model_validate(r) for r in result], meta=meta
        )

    def request_invoice(
        self,
        handler: Injected[RequestSaleInvoicingCommandHandler],
        sale_id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SaleResponse]:
        """Send a CONFIRMED sale to faclab-invoicing again, for when its invoice never
        arrived or the SRI rejected it. Invoicing ignores the request while the sale
        has an invoice in progress, and publishes the result again when it already
        authorized it. Resolves the sale's reconciliation discrepancy and is
        recorded in the audit log. 400 `INVALID_SALE_STATUS` for any other status,
        400 `INVOICING_DISABLED` when Kafka is off."""
        result = handler.handle(RequestSaleInvoicingCommand(sale_id=sale_id))
        return DataResponse(data=SaleResponse.model_validate(result), meta=meta)
