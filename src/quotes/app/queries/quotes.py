from dataclasses import dataclass

from wireup import injectable

from src.pos.terminal.app.scope import branch_scope
from src.quotes.app.document import QuoteDocuments
from src.quotes.app.repositories import QuoteFilter, QuoteRepository
from src.quotes.app.views import QuoteViews, quote_in_scope
from src.quotes.domain.entities import QuoteStatus
from src.shared.app.queries import Query, QueryHandler


@dataclass
class GetQuotesQuery(Query):
    status: QuoteStatus | None = None
    customer_id: int | None = None
    branch_id: int | None = None
    number: str | None = None
    limit: int | None = None
    offset: int | None = None
    branch_ids: frozenset[int] | None = None


@injectable(lifetime="scoped")
class GetQuotesQueryHandler(QueryHandler[GetQuotesQuery, dict]):
    """Las cotizaciones de las sucursales del usuario, las últimas primero"""

    def __init__(self, quotes: QuoteRepository, views: QuoteViews):
        self.quotes = quotes
        self.views = views

    def _handle(self, query: GetQuotesQuery) -> dict:
        page = self.quotes.page(
            QuoteFilter(
                status=query.status,
                customer_id=query.customer_id,
                branch_ids=branch_scope(query.branch_id, query.branch_ids),
                number=query.number,
            ),
            query.limit,
            query.offset,
        )
        return {**page, "items": self.views.summaries(page["items"])}


@dataclass
class GetQuoteQuery(Query):
    quote_id: int
    branch_ids: frozenset[int] | None = None


@injectable(lifetime="scoped")
class GetQuoteQueryHandler(QueryHandler[GetQuoteQuery, dict]):
    def __init__(self, quotes: QuoteRepository, views: QuoteViews):
        self.quotes = quotes
        self.views = views

    def _handle(self, query: GetQuoteQuery) -> dict:
        return self.views.detail(
            quote_in_scope(self.quotes, query.quote_id, query.branch_ids)
        )


@dataclass(frozen=True)
class QuotePdf:
    filename: str
    content: bytes


@dataclass
class GetQuotePdfQuery(Query):
    quote_id: int
    branch_ids: frozenset[int] | None = None


@injectable(lifetime="scoped")
class GetQuotePdfQueryHandler(QueryHandler[GetQuotePdfQuery, QuotePdf]):
    """El PDF para imprimir o descargar, en cualquier estado"""

    def __init__(self, quotes: QuoteRepository, documents: QuoteDocuments):
        self.quotes = quotes
        self.documents = documents

    def _handle(self, query: GetQuotePdfQuery) -> QuotePdf:
        quote = quote_in_scope(self.quotes, query.quote_id, query.branch_ids)
        document, content = self.documents.pdf(quote)
        return QuotePdf(document.filename, content)
