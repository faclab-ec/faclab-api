from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from wireup import Injected

from src.auth.domain.entities import AuthenticatedUser
from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import get_current_user, require_permission
from src.pos.terminal.app.resolver import TerminalRequest
from src.pos.terminal.infra.dependencies import pos_terminal
from src.receivables.app.commands.payments import (
    RecordCustomerPaymentCommand,
    RecordCustomerPaymentCommandHandler,
)
from src.receivables.app.queries.receivables import (
    GetCustomerAccountQuery,
    GetCustomerAccountQueryHandler,
    GetCustomerPaymentQuery,
    GetCustomerPaymentQueryHandler,
    GetCustomerPaymentsQuery,
    GetCustomerPaymentsQueryHandler,
    GetCustomerStatementQuery,
    GetCustomerStatementQueryHandler,
    GetReceivableQuery,
    GetReceivableQueryHandler,
    GetReceivablesAgingQuery,
    GetReceivablesAgingQueryHandler,
    GetReceivablesQuery,
    GetReceivablesQueryHandler,
)
from src.receivables.infra.validators import (
    AgingResponse,
    CustomerAccountResponse,
    CustomerPaymentQueryParams,
    CustomerPaymentRequest,
    CustomerPaymentResponse,
    CustomerPaymentSummaryResponse,
    ReceivableDetailResponse,
    ReceivableQueryParams,
    ReceivableResponse,
    StatementQueryParams,
    StatementResponse,
)
from src.shared.domain.tenant import current_tenant
from src.shared.infra.dependencies import get_meta
from src.shared.infra.idempotency.requests import (
    Idempotency,
    IdempotentRequest,
    idempotent_request,
)
from src.shared.infra.validators import (
    RESPONSES_COMMAND,
    RESPONSES_LIST,
    RESPONSES_QUERY,
    DataResponse,
    Meta,
    PaginatedDataResponse,
)

_READ = [Depends(require_permission(Permission.RECEIVABLE_READ))]
_WRITE = [Depends(require_permission(Permission.RECEIVABLE_WRITE))]
_POS = [Depends(require_permission(Permission.POS_OPERATE))]


def _command(
    body: CustomerPaymentRequest, user: AuthenticatedUser
) -> RecordCustomerPaymentCommand:
    return RecordCustomerPaymentCommand(
        customer_id=body.customer_id,
        amount=body.amount,
        payment_method=body.payment_method,
        reference=body.reference,
        notes=body.notes,
        applications=(
            [a.model_dump() for a in body.applications] if body.applications else None
        ),
        received_by=user.display_name,
    )


class ReceivableRouter:
    """Cuentas por cobrar (S5.5) en /api/admin/receivables"""

    def __init__(self):
        self.router = APIRouter()
        self.router.get(
            "",
            response_model=PaginatedDataResponse[ReceivableResponse],
            summary="Get the receivables",
            responses=RESPONSES_LIST,
            dependencies=_READ,
        )(self.get_all)
        self.router.get(
            "/aging",
            response_model=DataResponse[AgingResponse],
            summary="Get the aging of the open balances by customer",
            responses=RESPONSES_QUERY,
            dependencies=_READ,
        )(self.aging)
        self.router.get(
            "/{id}",
            response_model=DataResponse[ReceivableDetailResponse],
            summary="Get a receivable with its payments and refunds",
            responses=RESPONSES_QUERY,
            dependencies=_READ,
        )(self.get_by_id)

    def get_all(
        self,
        handler: Injected[GetReceivablesQueryHandler],
        query_params: ReceivableQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[ReceivableResponse]:
        """The receivables of the sales on credit, the one due first first.
        `overdue=true` keeps the open ones past their due date."""
        result = handler.handle(
            GetReceivablesQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[ReceivableResponse.model_validate(r) for r in result["items"]],
            meta=meta.with_pagination(
                total=result["total"], limit=result["limit"], offset=result["offset"]
            ),
        )

    def aging(
        self,
        handler: Injected[GetReceivablesAgingQueryHandler],
        branch_id: int | None = None,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[AgingResponse]:
        """What each customer owes by days past due today: not yet due, 1–30,
        31–60, 61–90 and over 90. Each open receivable falls in one bucket, so
        the buckets add up to the total owed. `branch_id` keeps one branch's."""
        result = handler.handle(GetReceivablesAgingQuery(branch_id=branch_id))
        return DataResponse(data=AgingResponse.model_validate(result), meta=meta)

    def get_by_id(
        self,
        id: int,
        handler: Injected[GetReceivableQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ReceivableDetailResponse]:
        """A receivable and what lowered its balance: payments on account and
        refunds of its sale."""
        result = handler.handle(GetReceivableQuery(receivable_id=id))
        return DataResponse(
            data=ReceivableDetailResponse.model_validate(result), meta=meta
        )


class CustomerAccountRouter:
    """La cuenta de un cliente (S5.5) en /api/admin/customer-accounts"""

    def __init__(self):
        self.router = APIRouter()
        self.router.get(
            "/{customer_id}",
            response_model=DataResponse[CustomerAccountResponse],
            summary="Get a customer's credit and open receivables",
            responses=RESPONSES_QUERY,
            dependencies=_READ,
        )(self.get_account)
        self.router.get(
            "/{customer_id}/statement",
            response_model=DataResponse[StatementResponse],
            summary="Get a customer's statement of account",
            responses=RESPONSES_QUERY,
            dependencies=_READ,
        )(self.statement)

    def get_account(
        self,
        customer_id: int,
        handler: Injected[GetCustomerAccountQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CustomerAccountResponse]:
        """Its credit limit and terms, what it owes (and past due), what it has
        available and its open receivables."""
        result = handler.handle(GetCustomerAccountQuery(customer_id=customer_id))
        return DataResponse(
            data=CustomerAccountResponse.model_validate(result), meta=meta
        )

    def statement(
        self,
        customer_id: int,
        handler: Injected[GetCustomerStatementQueryHandler],
        query_params: StatementQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[StatementResponse]:
        """Its balance when the period starts, each sale on credit (charge),
        payment on account, refund credited and cancelled sale with the balance
        after it, and its balance when the period ends (what it owes today
        without `toDate`)."""
        result = handler.handle(
            GetCustomerStatementQuery(
                customer_id=customer_id,
                from_date=query_params.from_date,
                to_date=query_params.to_date,
            )
        )
        return DataResponse(data=StatementResponse.model_validate(result), meta=meta)


class CustomerPaymentRouter:
    """Abonos de clientes (S5.5) en /api/admin/customer-payments"""

    def __init__(self):
        self.router = APIRouter()
        self.router.post(
            "",
            response_model=DataResponse[CustomerPaymentResponse],
            status_code=status.HTTP_201_CREATED,
            summary="Record a payment on account outside the cash register",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.create)
        self.router.get(
            "",
            response_model=PaginatedDataResponse[CustomerPaymentSummaryResponse],
            summary="Get the payments on account",
            responses=RESPONSES_LIST,
            dependencies=_READ,
        )(self.get_all)
        self.router.get(
            "/{id}",
            response_model=DataResponse[CustomerPaymentResponse],
            summary="Get a payment on account and what it paid",
            responses=RESPONSES_QUERY,
            dependencies=_READ,
        )(self.get_by_id)

    def create(
        self,
        body: CustomerPaymentRequest,
        handler: Injected[RecordCustomerPaymentCommandHandler],
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CustomerPaymentResponse]:
        """A payment on account taken outside the cash register (a transfer, a
        check, cash at the office): it counts in no shift. Without
        `applications` it pays the receivable due first, then the next (FIFO);
        it can't exceed what the customer owes. Numbered per tenant
        (`AB-2026-0001`), in the branch of `X-Branch-Id` if any."""
        context = current_tenant()
        command = _command(body, user)
        command.branch_id = context.branch_id if context else None
        result = handler.handle(command)
        return DataResponse(
            data=CustomerPaymentResponse.model_validate(result), meta=meta
        )

    def get_all(
        self,
        handler: Injected[GetCustomerPaymentsQueryHandler],
        query_params: CustomerPaymentQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[CustomerPaymentSummaryResponse]:
        """The payments on account, the last one first."""
        result = handler.handle(
            GetCustomerPaymentsQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[
                CustomerPaymentSummaryResponse.model_validate(p)
                for p in result["items"]
            ],
            meta=meta.with_pagination(
                total=result["total"], limit=result["limit"], offset=result["offset"]
            ),
        )

    def get_by_id(
        self,
        id: int,
        handler: Injected[GetCustomerPaymentQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CustomerPaymentResponse]:
        """A payment on account and the receivables it paid."""
        result = handler.handle(GetCustomerPaymentQuery(customer_payment_id=id))
        return DataResponse(
            data=CustomerPaymentResponse.model_validate(result), meta=meta
        )


class POSCustomerAccountRouter:
    """El crédito de un cliente en el POS (S5.5) en /api/pos/customer-accounts"""

    def __init__(self):
        self.router = APIRouter()
        self.router.get(
            "/{customer_id}",
            response_model=DataResponse[CustomerAccountResponse],
            summary="Get a customer's available credit and open receivables",
            responses=RESPONSES_QUERY,
            dependencies=_POS,
        )(self.get_account)

    def get_account(
        self,
        customer_id: int,
        handler: Injected[GetCustomerAccountQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CustomerAccountResponse]:
        """Whether it may buy on credit and how much (`hasCredit`,
        `available`), and its open receivables to take a payment on account."""
        result = handler.handle(GetCustomerAccountQuery(customer_id=customer_id))
        return DataResponse(
            data=CustomerAccountResponse.model_validate(result), meta=meta
        )


class POSCustomerPaymentRouter:
    """Abonos en la caja (S5.5) en /api/pos/customer-payments"""

    def __init__(self):
        self.router = APIRouter()
        self.router.post(
            "",
            response_model=DataResponse[CustomerPaymentResponse],
            status_code=status.HTTP_201_CREATED,
            summary="Take a payment on account at the terminal",
            responses=RESPONSES_COMMAND,
            dependencies=_POS,
        )(self.create)

    def create(
        self,
        body: CustomerPaymentRequest,
        handler: Injected[RecordCustomerPaymentCommandHandler],
        idempotency: Injected[Idempotency],
        terminal: TerminalRequest = Depends(pos_terminal),
        user: AuthenticatedUser = Depends(get_current_user),
        idempotent: IdempotentRequest | None = Depends(idempotent_request),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CustomerPaymentResponse] | JSONResponse:
        """A payment on account taken at the terminal, in its open shift: in
        cash it counts in the shift's cash (`customerPayments` of the cash
        summary). Without `applications` it pays the receivable due first, then
        the next (FIFO); it can't exceed what the customer owes.

        Requires `Idempotency-Key`: a retry with it gets the same payment,
        recorded once.
        """

        def respond() -> DataResponse[CustomerPaymentResponse]:
            command = _command(body, user)
            command.terminal = terminal
            result = handler.handle(command)
            return DataResponse(
                data=CustomerPaymentResponse.model_validate(result), meta=meta
            )

        return idempotency.run(idempotent, respond)
