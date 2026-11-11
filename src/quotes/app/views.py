from typing import Any

from wireup import injectable

from src.catalog.product.app.presentations import ProductPresentations
from src.catalog.product.app.repositories import ProductRepository
from src.customers.app.repositories import CustomerRepository
from src.organization.app.repositories import BranchRepository
from src.pos.terminal.app.scope import in_scope
from src.quotes.app.repositories import QuoteItemRepository, QuoteRepository
from src.quotes.domain.entities import Quote, QuoteItem, QuoteStatus
from src.sales.app.repositories import SaleRepository
from src.shared.domain.exceptions import NotFoundError


def quote_in_scope(
    quotes: QuoteRepository,
    quote_id: int,
    scope: frozenset[int] | None,
    for_update: bool = False,
) -> Quote:
    """The quote, if the user may enter its branch: another one answers as one
    that doesn't exist. A write locks it, so a conversion can't run under it"""
    quote = (
        quotes.first_for_update(id=quote_id)
        if for_update
        else quotes.get_by_id(quote_id)
    )
    if quote is None or not in_scope(quote.branch_id, scope):
        raise NotFoundError(f"Quote with id {quote_id} not found")
    return quote


@injectable(lifetime="scoped")
class QuoteViews:
    """Las cotizaciones como las muestran las respuestas: con su cliente, su
    sucursal, sus ítems con producto y presentación y la venta en que se
    convirtieron"""

    def __init__(
        self,
        items: QuoteItemRepository,
        customers: CustomerRepository,
        branches: BranchRepository,
        products: ProductRepository,
        presentations: ProductPresentations,
        sales: SaleRepository,
    ):
        self.items = items
        self.customers = customers
        self.branches = branches
        self.products = products
        self.presentations = presentations
        self.sales = sales

    def summaries(self, quotes: list[Quote]) -> list[dict[str, Any]]:
        customers = {
            c.require_id(): c
            for c in self.customers.get_by_ids(
                q.customer_id for q in quotes if q.customer_id is not None
            )
        }
        branches = {
            b.require_id(): b
            for b in self.branches.get_by_ids(q.branch_id for q in quotes)
        }
        views = []
        for quote in quotes:
            customer = customers.get(quote.customer_id or 0)
            branch = branches.get(quote.branch_id)
            views.append(
                {
                    **quote.dict(),
                    "customer_name": customer.name if customer else None,
                    "customer_tax_id": customer.tax_id if customer else None,
                    "customer_email": customer.email if customer else None,
                    "branch_name": branch.name if branch else None,
                    "establishment_code": branch.establishment_code if branch else None,
                }
            )
        return views

    def detail(
        self, quote: Quote, items: list[QuoteItem] | None = None
    ) -> dict[str, Any]:
        if items is None:
            items = self.items.for_quote(quote.require_id())
        [view] = self.summaries([quote])
        view["items"] = self.lines(items)
        sale = (
            self.sales.first(quote_id=quote.id)
            if quote.status == QuoteStatus.CONVERTED
            else None
        )
        view["sale_id"] = sale.id if sale else None
        view["sale_number"] = sale.number if sale else None
        return view

    def lines(self, items: list[QuoteItem]) -> list[dict[str, Any]]:
        products = {
            p.require_id(): p
            for p in self.products.get_by_ids(i.product_id for i in items)
        }
        names = self.presentations.names(i.presentation_id for i in items)
        lines = []
        for item in items:
            product = products.get(item.product_id)
            lines.append(
                {
                    **item.dict(),
                    "subtotal": item.subtotal,
                    "base_quantity": item.base_quantity,
                    "product_name": product.name if product else None,
                    "product_sku": product.sku if product else None,
                    "presentation_name": names.get(item.presentation_id or 0),
                }
            )
        return lines
