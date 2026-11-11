from fastapi import APIRouter, Depends, Response
from wireup import Injected

from src.auth.domain.entities import AuthenticatedUser
from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import get_current_user, require_permission
from src.pos.terminal.app.resolver import TerminalRequest
from src.pos.terminal.infra.dependencies import pos_branch, pos_terminal
from src.quotes.app.commands.actions import (
    AcceptQuoteCommand,
    AcceptQuoteCommandHandler,
    EmailQuoteCommand,
    EmailQuoteCommandHandler,
    RenewQuoteCommand,
    RenewQuoteCommandHandler,
    SendQuoteCommand,
    SendQuoteCommandHandler,
)
from src.quotes.app.commands.items import (
    AddQuoteItemCommand,
    AddQuoteItemCommandHandler,
    RemoveQuoteItemCommand,
    RemoveQuoteItemCommandHandler,
    UpdateQuoteItemCommand,
    UpdateQuoteItemCommandHandler,
)
from src.quotes.app.commands.quotes import (
    CreateQuoteCommand,
    CreateQuoteCommandHandler,
    DeleteQuoteCommand,
    DeleteQuoteCommandHandler,
    UpdateQuoteCommand,
    UpdateQuoteCommandHandler,
)
from src.quotes.app.queries.pos import (
    GetPosQuoteQuery,
    GetPosQuoteQueryHandler,
    GetPosQuotesQuery,
    GetPosQuotesQueryHandler,
)
from src.quotes.app.queries.quotes import (
    GetQuotePdfQuery,
    GetQuotePdfQueryHandler,
    GetQuoteQuery,
    GetQuoteQueryHandler,
    GetQuotesQuery,
    GetQuotesQueryHandler,
)
from src.quotes.infra.validators import (
    EmailQuoteRequest,
    PosQuoteQueryParams,
    PosQuoteResponse,
    QuoteItemRequest,
    QuoteItemUpdateRequest,
    QuoteQueryParams,
    QuoteRequest,
    QuoteResponse,
    QuoteSummaryResponse,
    QuoteUpdateRequest,
    RenewQuoteRequest,
)
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import (
    RESPONSES_COMMAND,
    RESPONSES_DELETE,
    RESPONSES_LIST,
    RESPONSES_QUERY,
    DataResponse,
    Meta,
    PaginatedDataResponse,
)

# Who sells quotes: the same roles that sell
_READ = [Depends(require_permission(Permission.SALE_READ))]
_WRITE = [Depends(require_permission(Permission.SALE_WRITE))]


class QuoteRouter:
    """Cotizaciones (S5.4) en /api/admin/quotes"""

    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        route = self.router
        route.get(
            "",
            response_model=PaginatedDataResponse[QuoteSummaryResponse],
            summary="Get the quotes",
            responses=RESPONSES_LIST,
            dependencies=_READ,
        )(self.get_all)
        route.post(
            "",
            response_model=DataResponse[QuoteResponse],
            summary="Create a quote",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.create)
        route.get(
            "/{id}",
            response_model=DataResponse[QuoteResponse],
            summary="Get a quote",
            responses=RESPONSES_QUERY,
            dependencies=_READ,
        )(self.get_by_id)
        route.put(
            "/{id}",
            response_model=DataResponse[QuoteResponse],
            summary="Update a draft quote",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.update)
        route.delete(
            "/{id}",
            summary="Delete a draft quote",
            responses=RESPONSES_DELETE,
            dependencies=_WRITE,
        )(self.delete)
        route.get(
            "/{id}/pdf",
            summary="Download the quote as PDF",
            responses={
                200: {"content": {"application/pdf": {}}, "description": "The PDF"},
                **RESPONSES_QUERY,
            },
            response_class=Response,
            dependencies=_READ,
        )(self.pdf)
        route.post(
            "/{id}/items",
            response_model=DataResponse[QuoteResponse],
            summary="Add an item to a draft quote",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.add_item)
        route.put(
            "/{id}/items/{item_id}",
            response_model=DataResponse[QuoteResponse],
            summary="Update an item of a draft quote",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.update_item)
        route.delete(
            "/{id}/items/{item_id}",
            response_model=DataResponse[QuoteResponse],
            summary="Remove an item of a draft quote",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.remove_item)
        route.post(
            "/{id}/send",
            response_model=DataResponse[QuoteResponse],
            summary="Mark a quote as sent",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.send)
        route.post(
            "/{id}/email",
            response_model=DataResponse[QuoteResponse],
            summary="Send a quote by email as PDF",
            responses={
                **RESPONSES_COMMAND,
                502: {"description": "The SMTP server refused it or is down"},
            },
            dependencies=_WRITE,
        )(self.email)
        route.post(
            "/{id}/accept",
            response_model=DataResponse[QuoteResponse],
            summary="Mark a quote as accepted by the customer",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.accept)
        route.post(
            "/{id}/renew",
            response_model=DataResponse[QuoteResponse],
            summary="Renew an expired quote",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.renew)

    def get_all(
        self,
        handler: Injected[GetQuotesQueryHandler],
        query_params: QuoteQueryParams = Depends(),
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[QuoteSummaryResponse]:
        """The quotes of the branches the user may enter, newest first."""
        result = handler.handle(
            GetQuotesQuery(
                **query_params.model_dump(exclude_none=True),
                branch_ids=user.branch_ids,
            )
        )
        return PaginatedDataResponse(
            data=[QuoteSummaryResponse.model_validate(q) for q in result["items"]],
            meta=meta.with_pagination(
                total=result["total"], limit=result["limit"], offset=result["offset"]
            ),
        )

    def create(
        self,
        body: QuoteRequest,
        handler: Injected[CreateQuoteCommandHandler],
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[QuoteResponse]:
        """Creates a draft quote in a branch, numbered there (`COT-001-000012`).
        Its items take the prices of the customer's list, the branch's or the
        general one, as a sale would today."""
        result = handler.handle(
            CreateQuoteCommand(
                **dict(body),
                created_by=user.display_name,
                branch_ids=user.branch_ids,
            )
        )
        return DataResponse(data=QuoteResponse.model_validate(result), meta=meta)

    def get_by_id(
        self,
        id: int,
        handler: Injected[GetQuoteQueryHandler],
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[QuoteResponse]:
        result = handler.handle(GetQuoteQuery(quote_id=id, branch_ids=user.branch_ids))
        return DataResponse(data=QuoteResponse.model_validate(result), meta=meta)

    def update(
        self,
        id: int,
        body: QuoteUpdateRequest,
        handler: Injected[UpdateQuoteCommandHandler],
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[QuoteResponse]:
        """Replaces a draft's customer, validity and notes. With another
        customer its items take the prices of that customer's lists."""
        result = handler.handle(
            UpdateQuoteCommand(quote_id=id, **dict(body), branch_ids=user.branch_ids)
        )
        return DataResponse(data=QuoteResponse.model_validate(result), meta=meta)

    def delete(
        self,
        id: int,
        handler: Injected[DeleteQuoteCommandHandler],
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> None:
        """Deletes a draft; its number is not used again."""
        handler.handle(DeleteQuoteCommand(quote_id=id, branch_ids=user.branch_ids))

    def pdf(
        self,
        id: int,
        handler: Injected[GetQuotePdfQueryHandler],
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> Response:
        """The quote to print or hand over, in any status."""
        result = handler.handle(
            GetQuotePdfQuery(quote_id=id, branch_ids=user.branch_ids)
        )
        return Response(
            content=result.content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{result.filename}"'
            },
        )

    def add_item(
        self,
        id: int,
        body: QuoteItemRequest,
        handler: Injected[AddQuoteItemCommandHandler],
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[QuoteResponse]:
        """Adds a line at the price its lists give today (a quote takes no
        price by hand; `PRODUCT_WITHOUT_PRICE` when there is none). Answers the
        quote with its new totals."""
        result = handler.handle(
            # dict() keeps the Decimals that model_dump() turns into floats
            AddQuoteItemCommand(quote_id=id, **dict(body), branch_ids=user.branch_ids)
        )
        return DataResponse(data=QuoteResponse.model_validate(result), meta=meta)

    def update_item(
        self,
        id: int,
        item_id: int,
        body: QuoteItemUpdateRequest,
        handler: Injected[UpdateQuoteItemCommandHandler],
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[QuoteResponse]:
        """Another quantity (priced again, a volume tier may apply) or discount."""
        result = handler.handle(
            UpdateQuoteItemCommand(
                quote_id=id, item_id=item_id, **dict(body), branch_ids=user.branch_ids
            )
        )
        return DataResponse(data=QuoteResponse.model_validate(result), meta=meta)

    def remove_item(
        self,
        id: int,
        item_id: int,
        handler: Injected[RemoveQuoteItemCommandHandler],
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[QuoteResponse]:
        result = handler.handle(
            RemoveQuoteItemCommand(
                quote_id=id, item_id=item_id, branch_ids=user.branch_ids
            )
        )
        return DataResponse(data=QuoteResponse.model_validate(result), meta=meta)

    def send(
        self,
        id: int,
        handler: Injected[SendQuoteCommandHandler],
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[QuoteResponse]:
        """A draft handed over to the customer (printed or by hand): `SENT`."""
        result = handler.handle(
            SendQuoteCommand(quote_id=id, branch_ids=user.branch_ids)
        )
        return DataResponse(data=QuoteResponse.model_validate(result), meta=meta)

    def email(
        self,
        id: int,
        body: EmailQuoteRequest,
        handler: Injected[EmailQuoteCommandHandler],
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[QuoteResponse]:
        """Sends its PDF to `to` or to the customer's email
        (`QUOTE_EMAIL_REQUIRED` without either): a draft becomes `SENT`, a sent
        or accepted one goes again. The SMTP server answers in the request: a
        refusal answers `EMAIL_DELIVERY_FAILED` (502) and nothing changes;
        `EMAIL_DISABLED` when email is off."""
        result = handler.handle(
            EmailQuoteCommand(quote_id=id, to=body.to, branch_ids=user.branch_ids)
        )
        return DataResponse(data=QuoteResponse.model_validate(result), meta=meta)

    def accept(
        self,
        id: int,
        handler: Injected[AcceptQuoteCommandHandler],
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[QuoteResponse]:
        """The customer accepted it: `ACCEPTED`, ready to be charged at the POS."""
        result = handler.handle(
            AcceptQuoteCommand(quote_id=id, branch_ids=user.branch_ids)
        )
        return DataResponse(data=QuoteResponse.model_validate(result), meta=meta)

    def renew(
        self,
        id: int,
        body: RenewQuoteRequest,
        handler: Injected[RenewQuoteCommandHandler],
        user: AuthenticatedUser = Depends(get_current_user),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[QuoteResponse]:
        """An expired quote in force again until `validUntil`: back to `DRAFT`,
        issued today and with today's prices."""
        result = handler.handle(
            RenewQuoteCommand(
                quote_id=id, valid_until=body.valid_until, branch_ids=user.branch_ids
            )
        )
        return DataResponse(data=QuoteResponse.model_validate(result), meta=meta)


class POSQuoteRouter:
    """Cotizaciones que el POS carga al carrito (S5.4) en /api/pos/quotes"""

    def __init__(self):
        self.router = APIRouter()
        _pos = [Depends(require_permission(Permission.POS_OPERATE))]
        self.router.get(
            "",
            response_model=PaginatedDataResponse[QuoteSummaryResponse],
            summary="Get the quotes in force of the branch",
            responses=RESPONSES_LIST,
            dependencies=_pos,
        )(self.get_all)
        self.router.get(
            "/{id}",
            response_model=DataResponse[PosQuoteResponse],
            summary="Get a quote to charge at the terminal",
            responses=RESPONSES_QUERY,
            dependencies=_pos,
        )(self.get_by_id)

    def get_all(
        self,
        handler: Injected[GetPosQuotesQueryHandler],
        query_params: PosQuoteQueryParams = Depends(),
        branch: TerminalRequest = Depends(pos_branch),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[QuoteSummaryResponse]:
        """The open quotes (draft, sent, accepted) of the branch in
        `X-Branch-Id` still in force today, newest first."""
        result = handler.handle(
            GetPosQuotesQuery(
                request=branch, **query_params.model_dump(exclude_none=True)
            )
        )
        return PaginatedDataResponse(
            data=[QuoteSummaryResponse.model_validate(q) for q in result["items"]],
            meta=meta.with_pagination(
                total=result["total"], limit=result["limit"], offset=result["offset"]
            ),
        )

    def get_by_id(
        self,
        id: int,
        handler: Injected[GetPosQuoteQueryHandler],
        terminal: TerminalRequest = Depends(pos_terminal),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[PosQuoteResponse]:
        """A quote of the terminal's branch with what charging it finds today:
        whether it expired, each line's price today (`listPrice`; a quoted one
        other than it goes as a price override with its reason) and the stock
        available at the terminal's location. Charge it with
        `POST /api/pos/sales/quick` and its `quoteId`, with its same items."""
        result = handler.handle(GetPosQuoteQuery(quote_id=id, request=terminal))
        return DataResponse(data=PosQuoteResponse.model_validate(result), meta=meta)
