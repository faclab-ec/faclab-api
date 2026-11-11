"""Las cotizaciones que el POS carga al carrito (S5.4): las vigentes de la
sucursal y, de una, lo que su conversión encontraría hoy en la terminal."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from wireup import injectable

from src.catalog.product.app.presentations import ProductPresentations
from src.catalog.product.app.repositories import (
    ProductPresentationRepository,
    ProductRepository,
)
from src.inventory.stock.app.repositories import StockRepository
from src.pos.terminal.app.resolver import TerminalRequest, TerminalResolver
from src.pricing.app.resolver import PriceLine, PriceResolver
from src.quotes.app.repositories import (
    QuoteFilter,
    QuoteItemRepository,
    QuoteRepository,
)
from src.quotes.app.views import QuoteViews
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class GetPosQuotesQuery(Query):
    request: TerminalRequest
    search: str | None = None
    limit: int | None = None
    offset: int | None = None


@injectable(lifetime="scoped")
class GetPosQuotesQueryHandler(QueryHandler[GetPosQuotesQuery, dict]):
    """Las cotizaciones abiertas y vigentes de la sucursal, las últimas primero"""

    def __init__(self, quotes: QuoteRepository, views: QuoteViews):
        self.quotes = quotes
        self.views = views

    def _handle(self, query: GetPosQuotesQuery) -> dict:
        page = self.quotes.page(
            QuoteFilter(
                branch_ids=frozenset({query.request.branch_id}),
                search=query.search,
                in_force_on=date.today(),
            ),
            query.limit,
            query.offset,
        )
        return {**page, "items": self.views.summaries(page["items"])}


@dataclass
class GetPosQuoteQuery(Query):
    quote_id: int
    request: TerminalRequest


@injectable(lifetime="scoped")
class GetPosQuoteQueryHandler(QueryHandler[GetPosQuoteQuery, dict]):
    """Una cotización de la sucursal con lo que el cajero necesita antes de
    cobrarla: si venció, el precio de lista de hoy de cada línea (frente al
    cotizado) y el stock disponible en la ubicación de la terminal, leído sin
    bloquear: la venta lo vuelve a comprobar al descontarlo."""

    def __init__(
        self,
        quotes: QuoteRepository,
        items: QuoteItemRepository,
        terminals: TerminalResolver,
        products: ProductRepository,
        presentation_repo: ProductPresentationRepository,
        presentations: ProductPresentations,
        prices: PriceResolver,
        stock: StockRepository,
        views: QuoteViews,
    ):
        self.quotes = quotes
        self.items = items
        self.terminals = terminals
        self.products = products
        self.presentation_repo = presentation_repo
        self.presentations = presentations
        self.prices = prices
        self.stock = stock
        self.views = views

    def _handle(self, query: GetPosQuoteQuery) -> dict:
        terminal = self.terminals.terminal(query.request)
        quote = self.quotes.get_by_id(query.quote_id)
        if quote is None or quote.branch_id != terminal.branch_id:
            raise NotFoundError(f"Quote with id {query.quote_id} not found")
        items = self.items.for_quote(quote.require_id())
        view = self.views.detail(quote, items)
        today = date.today()
        view["expired"] = quote.is_expired(today)

        products = {
            p.require_id(): p
            for p in self.products.get_by_ids(i.product_id for i in items)
        }
        by_id = {
            p.require_id(): p
            for p in self.presentation_repo.get_by_ids(
                i.presentation_id for i in items if i.presentation_id is not None
            )
        }
        lines = [
            PriceLine(
                products[item.product_id],
                by_id.get(item.presentation_id or 0)
                or self.presentations.resolve(products[item.product_id], None),
                item.quantity,
            )
            for item in items
        ]
        chain = self.prices.chain(quote.customer_id, quote.branch_id, today)
        resolved = self.prices.prices(chain, lines) if lines else []

        # What the lines of each product take together, like TerminalStock.take
        needed: dict[int, Decimal] = defaultdict(Decimal)
        for item in items:
            needed[item.product_id] += item.base_quantity
        available: dict[int, Decimal] = {}
        for product_id in needed:
            row = self.stock.first(
                product_id=product_id, location_id=terminal.default_location_id
            )
            available[product_id] = row.available_quantity if row else Decimal(0)

        for line, item, price in zip(view["items"], items, resolved, strict=True):
            line["list_price"] = price.unit_price
            line["price_list_name"] = price.price_list_name
            line["price_changed"] = (
                price.unit_price is not None and price.unit_price != item.unit_price
            )
            line["available_quantity"] = available[item.product_id]
            line["enough_stock"] = available[item.product_id] >= needed[item.product_id]
        return view
