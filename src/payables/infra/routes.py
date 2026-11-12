from fastapi import APIRouter, Depends, status
from wireup import Injected

from src.auth.domain.entities import AuthenticatedUser
from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import get_current_user, require_permission
from src.payables.app.commands.payments import (
    RecordSupplierPaymentCommand,
    RecordSupplierPaymentCommandHandler,
)
from src.payables.app.queries.payables import (
    GetPayableQuery,
    GetPayableQueryHandler,
    GetPayablesQuery,
    GetPayablesQueryHandler,
    GetSupplierAccountQuery,
    GetSupplierAccountQueryHandler,
    GetSupplierPaymentQuery,
    GetSupplierPaymentQueryHandler,
    GetSupplierPaymentsQuery,
    GetSupplierPaymentsQueryHandler,
)
from src.payables.infra.validators import (
    PayableDetailResponse,
    PayableQueryParams,
    PayableResponse,
    SupplierAccountResponse,
    SupplierPaymentQueryParams,
    SupplierPaymentRequest,
    SupplierPaymentResponse,
    SupplierPaymentSummaryResponse,
)
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import (
    RESPONSES_COMMAND,
    RESPONSES_LIST,
    RESPONSES_QUERY,
    DataResponse,
    Meta,
    PaginatedDataResponse,
)

_READ = [Depends(require_permission(Permission.PAYABLE_READ))]
_WRITE = [Depends(require_permission(Permission.PAYABLE_WRITE))]


class PayableRouter:
    """Cuentas por pagar (S5.7) en /api/admin/payables"""

    def __init__(self):
        self.router = APIRouter()
        self.router.get(
            "",
            response_model=PaginatedDataResponse[PayableResponse],
            summary="Get the accounts payable",
            responses=RESPONSES_LIST,
            dependencies=_READ,
        )(self.get_all)
        self.router.get(
            "/{id}",
            response_model=DataResponse[PayableDetailResponse],
            summary="Get an account payable with its payments and returns",
            responses=RESPONSES_QUERY,
            dependencies=_READ,
        )(self.get_by_id)

    def get_all(
        self,
        handler: Injected[GetPayablesQueryHandler],
        query_params: PayableQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[PayableResponse]:
        """What is owed for each purchase receipt, the one due first first.
        `overdue=true` keeps the open ones past their due date."""
        result = handler.handle(
            GetPayablesQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[PayableResponse.model_validate(p) for p in result["items"]],
            meta=meta.with_pagination(
                total=result["total"], limit=result["limit"], offset=result["offset"]
            ),
        )

    def get_by_id(
        self,
        id: int,
        handler: Injected[GetPayableQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[PayableDetailResponse]:
        """An account payable and what lowered its balance: payments to the
        supplier and supplier returns."""
        result = handler.handle(GetPayableQuery(payable_id=id))
        return DataResponse(
            data=PayableDetailResponse.model_validate(result), meta=meta
        )


class SupplierAccountRouter:
    """Lo que se le debe a un proveedor (S5.7) en /api/admin/supplier-accounts"""

    def __init__(self):
        self.router = APIRouter()
        self.router.get(
            "/{supplier_id}",
            response_model=DataResponse[SupplierAccountResponse],
            summary="Get what is owed to a supplier and its open payables",
            responses=RESPONSES_QUERY,
            dependencies=_READ,
        )(self.get_account)

    def get_account(
        self,
        supplier_id: int,
        handler: Injected[GetSupplierAccountQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SupplierAccountResponse]:
        """What is owed (and past due), its open payables, its last payments and
        its confirmed returns with what they credited and what the supplier has
        to refund."""
        result = handler.handle(GetSupplierAccountQuery(supplier_id=supplier_id))
        return DataResponse(
            data=SupplierAccountResponse.model_validate(result), meta=meta
        )


class SupplierPaymentRouter:
    """Pagos a proveedores (S5.7) en /api/admin/supplier-payments"""

    def __init__(self):
        self.router = APIRouter()
        self.router.post(
            "",
            response_model=DataResponse[SupplierPaymentResponse],
            status_code=status.HTTP_201_CREATED,
            summary="Record a payment to a supplier",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.create)
        self.router.get(
            "",
            response_model=PaginatedDataResponse[SupplierPaymentSummaryResponse],
            summary="Get the payments to suppliers",
            responses=RESPONSES_LIST,
            dependencies=_READ,
        )(self.get_all)
        self.router.get(
            "/{id}",
            response_model=DataResponse[SupplierPaymentResponse],
            summary="Get a payment to a supplier and what it paid",
            responses=RESPONSES_QUERY,
            dependencies=_READ,
        )(self.get_by_id)

    def create(
        self,
        body: SupplierPaymentRequest,
        handler: Injected[RecordSupplierPaymentCommandHandler],
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SupplierPaymentResponse]:
        """Without `applications` it pays the payable due first, then the next
        (FIFO); it can't exceed what is owed to the supplier. Numbered per
        tenant (`PP-2026-0001`)."""
        result = handler.handle(
            RecordSupplierPaymentCommand(
                supplier_id=body.supplier_id,
                amount=body.amount,
                payment_method=body.payment_method,
                reference=body.reference,
                notes=body.notes,
                applications=(
                    [a.model_dump() for a in body.applications]
                    if body.applications
                    else None
                ),
                paid_by=user.display_name,
            )
        )
        return DataResponse(
            data=SupplierPaymentResponse.model_validate(result), meta=meta
        )

    def get_all(
        self,
        handler: Injected[GetSupplierPaymentsQueryHandler],
        query_params: SupplierPaymentQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[SupplierPaymentSummaryResponse]:
        """The payments to suppliers, the last one first."""
        result = handler.handle(
            GetSupplierPaymentsQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[
                SupplierPaymentSummaryResponse.model_validate(p)
                for p in result["items"]
            ],
            meta=meta.with_pagination(
                total=result["total"], limit=result["limit"], offset=result["offset"]
            ),
        )

    def get_by_id(
        self,
        id: int,
        handler: Injected[GetSupplierPaymentQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SupplierPaymentResponse]:
        result = handler.handle(GetSupplierPaymentQuery(supplier_payment_id=id))
        return DataResponse(
            data=SupplierPaymentResponse.model_validate(result), meta=meta
        )
