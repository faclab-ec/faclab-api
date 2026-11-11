from src.quotes.app.commands.actions import (
    AcceptQuoteCommandHandler,
    EmailQuoteCommandHandler,
    RenewQuoteCommandHandler,
    SendQuoteCommandHandler,
)
from src.quotes.app.commands.items import (
    AddQuoteItemCommandHandler,
    RemoveQuoteItemCommandHandler,
    UpdateQuoteItemCommandHandler,
)
from src.quotes.app.commands.quotes import (
    CreateQuoteCommandHandler,
    DeleteQuoteCommandHandler,
    UpdateQuoteCommandHandler,
)
from src.quotes.app.conversion import QuoteConversion
from src.quotes.app.document import QuoteDocuments
from src.quotes.app.pricing import QuotePricing
from src.quotes.app.queries.pos import GetPosQuoteQueryHandler, GetPosQuotesQueryHandler
from src.quotes.app.queries.quotes import (
    GetQuotePdfQueryHandler,
    GetQuoteQueryHandler,
    GetQuotesQueryHandler,
)
from src.quotes.app.views import QuoteViews
from src.quotes.infra.mappers import QuoteItemMapper, QuoteMapper
from src.quotes.infra.pdf import ReportLabQuoteRenderer
from src.quotes.infra.repositories import (
    SqlAlchemyQuoteItemRepository,
    SqlAlchemyQuoteRepository,
)

INJECTABLES = [
    QuoteMapper,
    QuoteItemMapper,
    SqlAlchemyQuoteRepository,
    SqlAlchemyQuoteItemRepository,
    ReportLabQuoteRenderer,
    QuoteViews,
    QuotePricing,
    QuoteDocuments,
    QuoteConversion,
    CreateQuoteCommandHandler,
    UpdateQuoteCommandHandler,
    DeleteQuoteCommandHandler,
    AddQuoteItemCommandHandler,
    UpdateQuoteItemCommandHandler,
    RemoveQuoteItemCommandHandler,
    SendQuoteCommandHandler,
    AcceptQuoteCommandHandler,
    RenewQuoteCommandHandler,
    EmailQuoteCommandHandler,
    GetQuotesQueryHandler,
    GetQuoteQueryHandler,
    GetQuotePdfQueryHandler,
    GetPosQuotesQueryHandler,
    GetPosQuoteQueryHandler,
]
