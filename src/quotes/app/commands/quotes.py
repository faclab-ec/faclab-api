from dataclasses import dataclass
from datetime import date

from wireup import injectable

from src.auth.domain.exceptions import BranchAccessDeniedError
from src.customers.app.repositories import CustomerRepository
from src.organization.app.numbering import DocumentNumbering
from src.organization.app.repositories import BranchRepository
from src.organization.domain.exceptions import BranchInactiveError
from src.organization.domain.numbering import DocumentType
from src.quotes.app.pricing import QuotePricing
from src.quotes.app.repositories import QuoteItemRepository, QuoteRepository
from src.quotes.app.views import QuoteViews, quote_in_scope
from src.quotes.domain.entities import Quote
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError


def ensure_customer(customers: CustomerRepository, customer_id: int | None) -> None:
    if customer_id is not None and customers.get_by_id(customer_id) is None:
        raise NotFoundError(f"Customer with id {customer_id} not found")


@dataclass
class CreateQuoteCommand(Command):
    branch_id: int
    valid_until: date
    customer_id: int | None = None
    notes: str | None = None
    created_by: str | None = None
    # The branches the user may enter (None: all)
    branch_ids: frozenset[int] | None = None


@injectable(lifetime="scoped")
class CreateQuoteCommandHandler(CommandHandler[CreateQuoteCommand, dict]):
    """Una cotización nueva en borrador, numerada en su sucursal"""

    def __init__(
        self,
        quotes: QuoteRepository,
        branches: BranchRepository,
        customers: CustomerRepository,
        numbering: DocumentNumbering,
        views: QuoteViews,
    ):
        self.quotes = quotes
        self.branches = branches
        self.customers = customers
        self.numbering = numbering
        self.views = views

    def _handle(self, command: CreateQuoteCommand) -> dict:
        if (
            command.branch_ids is not None
            and command.branch_id not in command.branch_ids
        ):
            raise BranchAccessDeniedError()
        branch = self.branches.get_by_id(command.branch_id)
        if branch is None:
            raise NotFoundError(f"Branch {command.branch_id} not found")
        if not branch.is_active:
            raise BranchInactiveError(command.branch_id)
        ensure_customer(self.customers, command.customer_id)
        quote = Quote.draft(
            branch_id=command.branch_id,
            valid_until=command.valid_until,
            today=date.today(),
            customer_id=command.customer_id,
            notes=command.notes,
            created_by=command.created_by,
        )
        # The branch's counter, locked until the quote commits; a deleted draft
        # keeps its number, like a purchase order's
        quote.number = self.numbering.next(command.branch_id, DocumentType.QUOTE)
        quote = self.quotes.create(quote)
        return self.views.detail(quote, [])


@dataclass
class UpdateQuoteCommand(Command):
    quote_id: int
    valid_until: date
    customer_id: int | None = None
    notes: str | None = None
    branch_ids: frozenset[int] | None = None


@injectable(lifetime="scoped")
class UpdateQuoteCommandHandler(CommandHandler[UpdateQuoteCommand, dict]):
    """Los datos de un borrador; con otro cliente, sus líneas toman los precios
    de las listas de ese cliente"""

    def __init__(
        self,
        quotes: QuoteRepository,
        items: QuoteItemRepository,
        customers: CustomerRepository,
        pricing: QuotePricing,
        views: QuoteViews,
    ):
        self.quotes = quotes
        self.items = items
        self.customers = customers
        self.pricing = pricing
        self.views = views

    def _handle(self, command: UpdateQuoteCommand) -> dict:
        quote = quote_in_scope(
            self.quotes, command.quote_id, command.branch_ids, for_update=True
        )
        ensure_customer(self.customers, command.customer_id)
        today = date.today()
        customer_changed = command.customer_id != quote.customer_id
        quote.change(
            customer_id=command.customer_id,
            valid_until=command.valid_until,
            notes=command.notes,
            today=today,
        )
        items = self.items.for_quote(quote.require_id())
        if customer_changed:
            self.pricing.reprice(quote, items, today)
            for item in items:
                self.items.update(item)
            quote.recalculate_totals(items)
        quote = self.quotes.update(quote)
        return self.views.detail(quote, items)


@dataclass
class DeleteQuoteCommand(Command):
    quote_id: int
    branch_ids: frozenset[int] | None = None


@injectable(lifetime="scoped")
class DeleteQuoteCommandHandler(CommandHandler[DeleteQuoteCommand, None]):
    """Borra un borrador con sus ítems; su número no se vuelve a usar"""

    def __init__(self, quotes: QuoteRepository):
        self.quotes = quotes

    def _handle(self, command: DeleteQuoteCommand) -> None:
        quote = quote_in_scope(
            self.quotes, command.quote_id, command.branch_ids, for_update=True
        )
        quote.ensure_draft("delete")
        self.quotes.delete(quote.require_id())
