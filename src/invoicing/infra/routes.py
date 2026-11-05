from fastapi import APIRouter, Depends, status
from wireup import Injected

from src.auth.domain.entities import AuthenticatedUser
from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import get_current_user, require_permission
from src.invoicing.app.commands.credit_notes import (
    RequestCancelledSaleCreditNoteCommand,
    RequestCancelledSaleCreditNoteCommandHandler,
    RequestCreditNoteAgainCommand,
    RequestCreditNoteAgainCommandHandler,
)
from src.invoicing.app.commands.discrepancies import (
    ReviewInvoiceDiscrepancyCommand,
    ReviewInvoiceDiscrepancyCommandHandler,
)
from src.invoicing.app.queries.discrepancies import (
    ListInvoiceDiscrepanciesQuery,
    ListInvoiceDiscrepanciesQueryHandler,
)
from src.invoicing.infra.validators import (
    CreditNoteResponse,
    InvoiceDiscrepancyQueryParams,
    InvoiceDiscrepancyResponse,
    RequestCancelledSaleCreditNoteRequest,
    ReviewInvoiceDiscrepancyRequest,
)
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import (
    RESPONSES_COMMAND,
    RESPONSES_LIST,
    DataResponse,
    Meta,
    PaginatedDataResponse,
)


class InvoiceDiscrepancyRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        self.router.get(
            "",
            response_model=PaginatedDataResponse[InvoiceDiscrepancyResponse],
            summary="List invoice discrepancies",
            responses=RESPONSES_LIST,
            dependencies=[Depends(require_permission(Permission.SALE_READ))],
        )(self.get_all)
        self.router.post(
            "/{discrepancy_id}/review",
            response_model=DataResponse[InvoiceDiscrepancyResponse],
            summary="Mark an invoice discrepancy as reviewed",
            responses=RESPONSES_COMMAND,
            dependencies=[Depends(require_permission(Permission.SALE_WRITE))],
        )(self.review)
        self.router.post(
            "/{discrepancy_id}/credit-note",
            response_model=DataResponse[CreditNoteResponse],
            status_code=status.HTTP_201_CREATED,
            summary="Ask for the credit note of the invoice of a cancelled sale",
            responses=RESPONSES_COMMAND,
            dependencies=[Depends(require_permission(Permission.SALE_WRITE))],
        )(self.request_credit_note)

    def get_all(
        self,
        handler: Injected[ListInvoiceDiscrepanciesQueryHandler],
        query_params: InvoiceDiscrepancyQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[InvoiceDiscrepancyResponse]:
        """
        Sales of the tenant that don't square with faclab-invoicing, oldest first:
        confirmed without an invoice result after the threshold, or with an invoice
        the SRI authorized after the sale was cancelled. The worker's reconciliation
        opens and resolves them. Only open ones unless `status` says otherwise.
        """
        result = handler.handle(
            ListInvoiceDiscrepanciesQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[
                InvoiceDiscrepancyResponse.model_validate(item)
                for item in result["items"]
            ],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )

    def review(
        self,
        handler: Injected[ReviewInvoiceDiscrepancyCommandHandler],
        discrepancy_id: int,
        request: ReviewInvoiceDiscrepancyRequest,
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[InvoiceDiscrepancyResponse]:
        """
        A user takes an open discrepancy: it leaves the open list and stays reviewed
        until its condition goes away. The reviewer comes from the token. Recorded
        in the audit log. 409 `INVOICE_DISCREPANCY_NOT_OPEN` if it isn't open.
        """
        result = handler.handle(
            ReviewInvoiceDiscrepancyCommand(
                discrepancy_id=discrepancy_id,
                user_id=user.id,
                user_name=user.display_name,
                note=request.note,
            )
        )
        return DataResponse(
            data=InvoiceDiscrepancyResponse.model_validate(result), meta=meta
        )

    def request_credit_note(
        self,
        handler: Injected[RequestCancelledSaleCreditNoteCommandHandler],
        discrepancy_id: int,
        request: RequestCancelledSaleCreditNoteRequest,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CreditNoteResponse]:
        """
        The SRI authorized the invoice of a sale that was already cancelled: this asks
        for the credit note of the whole invoice (the stock and the money went back
        with the cancellation). Recorded in the audit log; the discrepancy is resolved
        once the SRI authorizes it. 409 `CREDIT_NOTE_NOT_APPLICABLE` for any other
        discrepancy, `CREDIT_NOTE_ALREADY_REQUESTED` if it has one (ask for it again
        instead) and `FINAL_CONSUMER_CREDIT_NOTE_NOT_ALLOWED` for an invoice to the
        final consumer, which admits none: it stays for a manual review.
        """
        result = handler.handle(
            RequestCancelledSaleCreditNoteCommand(
                discrepancy_id=discrepancy_id, reason=request.reason
            )
        )
        return DataResponse(data=CreditNoteResponse.model_validate(result), meta=meta)


class CreditNoteRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        self.router.post(
            "/{credit_note_id}/request-again",
            response_model=DataResponse[CreditNoteResponse],
            summary="Ask for a credit note again",
            responses=RESPONSES_COMMAND,
            dependencies=[Depends(require_permission(Permission.SALE_WRITE))],
        )(self.request_again)

    def request_again(
        self,
        handler: Injected[RequestCreditNoteAgainCommandHandler],
        credit_note_id: int,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CreditNoteResponse]:
        """
        After a rejection faclab-invoicing issues another one, with another number; if
        its result never arrived, it publishes it again. Recorded in the audit log.
        409 `CREDIT_NOTE_ALREADY_AUTHORIZED` once it is authorized.
        """
        result = handler.handle(
            RequestCreditNoteAgainCommand(credit_note_id=credit_note_id)
        )
        return DataResponse(data=CreditNoteResponse.model_validate(result), meta=meta)
