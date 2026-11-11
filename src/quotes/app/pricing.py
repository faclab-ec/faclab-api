from datetime import date
from decimal import Decimal

from wireup import injectable

from src.catalog.product.app.presentations import ProductPresentations
from src.catalog.product.app.repositories import (
    ProductPresentationRepository,
    ProductRepository,
)
from src.catalog.product.domain.entities import Product, ProductPresentation
from src.pricing.app.resolver import PriceLine, PriceResolver
from src.quotes.domain.entities import Quote, QuoteItem
from src.quotes.domain.exceptions import QuoteLineWithoutPriceError


@injectable(lifetime="scoped")
class QuotePricing:
    """El precio de las líneas de una cotización: el que tomaría hoy una venta de
    su cliente en su sucursal (S5.3), por lista o el de su presentación. Una
    cotización no lleva precios a mano."""

    def __init__(
        self,
        products: ProductRepository,
        presentation_repo: ProductPresentationRepository,
        presentations: ProductPresentations,
        prices: PriceResolver,
    ):
        self.products = products
        self.presentation_repo = presentation_repo
        self.presentations = presentations
        self.prices = prices

    def price(
        self,
        quote: Quote,
        product: Product,
        presentation: ProductPresentation,
        quantity: Decimal,
        today: date,
    ) -> Decimal:
        chain = self.prices.chain(quote.customer_id, quote.branch_id, today)
        resolved = self.prices.price(chain, product, presentation, quantity)
        if resolved.unit_price is None:
            raise QuoteLineWithoutPriceError(product.require_id())
        return resolved.unit_price

    def reprice(self, quote: Quote, items: list[QuoteItem], today: date) -> None:
        """Los precios de hoy y el IVA actual de su producto en cada línea: al
        renovarla o al cambiar su cliente"""
        if not items:
            return
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
        lines = []
        for item in items:
            product = products[item.product_id]
            # Its own presentation, even if it was deactivated after it was added
            presentation = by_id.get(item.presentation_id or 0)
            if presentation is None:
                presentation = self.presentations.resolve(product, None)
            lines.append(PriceLine(product, presentation, item.quantity))
        chain = self.prices.chain(quote.customer_id, quote.branch_id, today)
        for item, line, resolved in zip(
            items, lines, self.prices.prices(chain, lines), strict=True
        ):
            if resolved.unit_price is None:
                raise QuoteLineWithoutPriceError(item.product_id)
            item.unit_price = resolved.unit_price
            item.tax_code = line.product.tax_code
            item.recalculate_tax()
