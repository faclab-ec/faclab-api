from dataclasses import dataclass
from datetime import date

import structlog
from wireup import injectable

from src.quotes.app.document import QuoteDocument, QuoteDocuments
from src.quotes.app.pricing import QuotePricing
from src.quotes.app.repositories import QuoteItemRepository, QuoteRepository
from src.quotes.app.views import QuoteViews, quote_in_scope
from src.quotes.domain.exceptions import QuoteEmailRequiredError
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.mail import MailAttachment, Mailer, OutgoingMail
from src.shared.domain.value_objects import Email

logger = structlog.get_logger(__name__)


@dataclass
class SendQuoteCommand(Command):
    quote_id: int
    branch_ids: frozenset[int] | None = None


@injectable(lifetime="scoped")
class SendQuoteCommandHandler(CommandHandler[SendQuoteCommand, dict]):
    """Un borrador entregado al cliente a mano o impreso"""

    def __init__(
        self, quotes: QuoteRepository, items: QuoteItemRepository, views: QuoteViews
    ):
        self.quotes = quotes
        self.items = items
        self.views = views

    def _handle(self, command: SendQuoteCommand) -> dict:
        quote = quote_in_scope(
            self.quotes, command.quote_id, command.branch_ids, for_update=True
        )
        items = self.items.for_quote(quote.require_id())
        quote.send(len(items), date.today())
        return self.views.detail(self.quotes.update(quote), items)


@dataclass
class AcceptQuoteCommand(Command):
    quote_id: int
    branch_ids: frozenset[int] | None = None


@injectable(lifetime="scoped")
class AcceptQuoteCommandHandler(CommandHandler[AcceptQuoteCommand, dict]):
    def __init__(
        self, quotes: QuoteRepository, items: QuoteItemRepository, views: QuoteViews
    ):
        self.quotes = quotes
        self.items = items
        self.views = views

    def _handle(self, command: AcceptQuoteCommand) -> dict:
        quote = quote_in_scope(
            self.quotes, command.quote_id, command.branch_ids, for_update=True
        )
        items = self.items.for_quote(quote.require_id())
        quote.accept(len(items), date.today())
        return self.views.detail(self.quotes.update(quote), items)


@dataclass
class RenewQuoteCommand(Command):
    quote_id: int
    valid_until: date
    branch_ids: frozenset[int] | None = None


@injectable(lifetime="scoped")
class RenewQuoteCommandHandler(CommandHandler[RenewQuoteCommand, dict]):
    """Una vencida vuelve a regir: en borrador, emitida hoy y con los precios
    de hoy, porque los que cotizó dejaron de comprometer a la empresa"""

    def __init__(
        self,
        quotes: QuoteRepository,
        items: QuoteItemRepository,
        pricing: QuotePricing,
        views: QuoteViews,
    ):
        self.quotes = quotes
        self.items = items
        self.pricing = pricing
        self.views = views

    def _handle(self, command: RenewQuoteCommand) -> dict:
        quote = quote_in_scope(
            self.quotes, command.quote_id, command.branch_ids, for_update=True
        )
        today = date.today()
        quote.renew(command.valid_until, today)
        items = self.items.for_quote(quote.require_id())
        self.pricing.reprice(quote, items, today)
        for item in items:
            self.items.update(item)
        quote.recalculate_totals(items)
        return self.views.detail(self.quotes.update(quote), items)


@dataclass
class EmailQuoteCommand(Command):
    quote_id: int
    # None: the customer's email
    to: str | None = None
    branch_ids: frozenset[int] | None = None


@injectable(lifetime="scoped")
class EmailQuoteCommandHandler(CommandHandler[EmailQuoteCommand, dict]):
    """Envía el PDF por correo y la marca enviada. El correo sale al final, con
    la cotización ya guardada: si el servidor lo rechaza, la solicitud falla
    (`EMAIL_DELIVERY_FAILED`) y no queda marcada"""

    def __init__(
        self,
        quotes: QuoteRepository,
        items: QuoteItemRepository,
        documents: QuoteDocuments,
        mailer: Mailer,
        views: QuoteViews,
    ):
        self.quotes = quotes
        self.items = items
        self.documents = documents
        self.mailer = mailer
        self.views = views

    def _handle(self, command: EmailQuoteCommand) -> dict:
        quote = quote_in_scope(
            self.quotes, command.quote_id, command.branch_ids, for_update=True
        )
        items = self.items.for_quote(quote.require_id())
        quote.mark_emailed(len(items), date.today())
        quote = self.quotes.update(quote)
        document, pdf = self.documents.pdf(quote)
        to = command.to or document.customer_email
        if not to:
            raise QuoteEmailRequiredError()
        Email(to)
        self.mailer.send(
            OutgoingMail(
                to=to,
                subject=f"Cotización {document.number} · {document.sender_name}",
                text=quote_email_text(document),
                sender_name=document.sender_name,
                attachments=(MailAttachment(document.filename, pdf),),
            )
        )
        logger.info("quote_emailed", quote_id=quote.id)
        return self.views.detail(quote, items)


def quote_email_text(document: QuoteDocument) -> str:
    greeting = (
        f"Estimado(a) {document.customer_name}:"
        if document.customer_name
        else "Estimado(a) cliente:"
    )
    paragraphs = [
        greeting,
        f"Adjuntamos la cotización {document.number} de {document.sender_name} por "
        f"un total de ${document.total:,.2f}, válida hasta el "
        f"{document.valid_until:%d/%m/%Y}.",
    ]
    if document.notes:
        paragraphs.append(document.notes)
    paragraphs += [
        "Los precios rigen hasta esa fecha y la cotización no reserva mercadería.",
        f"{document.sender_name} · {document.branch_name}",
    ]
    return "\n\n".join(paragraphs) + "\n"
