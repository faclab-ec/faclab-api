from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from wireup import injectable

from src.catalog.product.app.presentations import ProductPresentations
from src.catalog.product.app.quantities import ProductQuantities
from src.catalog.product.app.repositories import ProductRepository
from src.quotes.app.pricing import QuotePricing
from src.quotes.app.repositories import QuoteItemRepository, QuoteRepository
from src.quotes.app.views import QuoteViews, quote_in_scope
from src.quotes.domain.entities import Quote, QuoteItem
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError


def _totals(quote: Quote, quotes: QuoteRepository, items: QuoteItemRepository) -> tuple:
    lines = items.for_quote(quote.require_id())
    quote.recalculate_totals(lines)
    return quotes.update(quote), lines


def _item_of(items: QuoteItemRepository, quote: Quote, item_id: int) -> QuoteItem:
    item = items.get_by_id(item_id)
    if item is None or item.quote_id != quote.id:
        raise NotFoundError(f"Item {item_id} of quote {quote.id} not found")
    return item


@dataclass
class AddQuoteItemCommand(Command):
    quote_id: int
    product_id: int
    quantity: Decimal
    # The presentation it is quoted in (S5.2); none: the base unit
    presentation_id: int | None = None
    # Percentage of the line, like a sale line's
    discount: Decimal = Decimal("0")
    branch_ids: frozenset[int] | None = None


@injectable(lifetime="scoped")
class AddQuoteItemCommandHandler(CommandHandler[AddQuoteItemCommand, dict]):
    """Una línea nueva al precio de hoy de sus listas"""

    def __init__(
        self,
        quotes: QuoteRepository,
        items: QuoteItemRepository,
        products: ProductRepository,
        presentations: ProductPresentations,
        quantities: ProductQuantities,
        pricing: QuotePricing,
        views: QuoteViews,
    ):
        self.quotes = quotes
        self.items = items
        self.products = products
        self.presentations = presentations
        self.quantities = quantities
        self.pricing = pricing
        self.views = views

    def _handle(self, command: AddQuoteItemCommand) -> dict:
        quote = quote_in_scope(
            self.quotes, command.quote_id, command.branch_ids, for_update=True
        )
        quote.ensure_draft("add items to")
        product = self.products.get_by_id(command.product_id)
        if product is None:
            raise NotFoundError(f"Product with id {command.product_id} not found")
        presentation = self.presentations.resolve(product, command.presentation_id)
        quantity = Decimal(command.quantity)
        self.quantities.ensure_for_presentation(product, presentation.factor, quantity)
        item = QuoteItem(
            quote_id=quote.require_id(),
            product_id=product.require_id(),
            quantity=quantity,
            unit_price=self.pricing.price(
                quote, product, presentation, quantity, date.today()
            ),
            discount=Decimal(str(command.discount)),
            tax_code=product.tax_code,
            presentation_id=presentation.id,
            unit_factor=presentation.factor,
        )
        item.recalculate_tax()
        self.items.create(item)
        quote, lines = _totals(quote, self.quotes, self.items)
        return self.views.detail(quote, lines)


@dataclass
class UpdateQuoteItemCommand(Command):
    quote_id: int
    item_id: int
    quantity: Decimal | None = None
    discount: Decimal | None = None
    branch_ids: frozenset[int] | None = None


@injectable(lifetime="scoped")
class UpdateQuoteItemCommandHandler(CommandHandler[UpdateQuoteItemCommand, dict]):
    """Otra cantidad (con el precio de su escala) o descuento de una línea"""

    def __init__(
        self,
        quotes: QuoteRepository,
        items: QuoteItemRepository,
        quantities: ProductQuantities,
        pricing: QuotePricing,
        views: QuoteViews,
    ):
        self.quotes = quotes
        self.items = items
        self.quantities = quantities
        self.pricing = pricing
        self.views = views

    def _handle(self, command: UpdateQuoteItemCommand) -> dict:
        quote = quote_in_scope(
            self.quotes, command.quote_id, command.branch_ids, for_update=True
        )
        quote.ensure_draft("update items in")
        item = _item_of(self.items, quote, command.item_id)
        if command.quantity is not None:
            quantity = Decimal(command.quantity)
            self.quantities.ensure_in_presentations(
                [(item.product_id, item.unit_factor, quantity)]
            )
            item.quantity = quantity
            self.pricing.reprice(quote, [item], date.today())
        if command.discount is not None:
            item.discount = Decimal(str(command.discount))
        item.recalculate_tax()
        self.items.update(item)
        quote, lines = _totals(quote, self.quotes, self.items)
        return self.views.detail(quote, lines)


@dataclass
class RemoveQuoteItemCommand(Command):
    quote_id: int
    item_id: int
    branch_ids: frozenset[int] | None = None


@injectable(lifetime="scoped")
class RemoveQuoteItemCommandHandler(CommandHandler[RemoveQuoteItemCommand, dict]):
    def __init__(
        self,
        quotes: QuoteRepository,
        items: QuoteItemRepository,
        views: QuoteViews,
    ):
        self.quotes = quotes
        self.items = items
        self.views = views

    def _handle(self, command: RemoveQuoteItemCommand) -> dict:
        quote = quote_in_scope(
            self.quotes, command.quote_id, command.branch_ids, for_update=True
        )
        quote.ensure_draft("remove items from")
        item = _item_of(self.items, quote, command.item_id)
        self.items.delete(item.require_id())
        quote, lines = _totals(quote, self.quotes, self.items)
        return self.views.detail(quote, lines)
