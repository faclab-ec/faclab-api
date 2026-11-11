from dataclasses import dataclass, field
from decimal import Decimal

from wireup import injectable

from src.catalog.product.app.presentations import ProductPresentations
from src.catalog.product.app.repositories import ProductRepository
from src.pricing.app.resolver import PriceLine, PriceResolver
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class PriceLineInput:
    product_id: int
    quantity: Decimal
    presentation_id: int | None = None


@dataclass
class ResolvePricesQuery(Query):
    branch_id: int
    customer_id: int | None = None
    items: list[PriceLineInput] = field(default_factory=list)


@injectable(lifetime="scoped")
class ResolvePricesQueryHandler(QueryHandler[ResolvePricesQuery, list[dict]]):
    """El precio que tomaría cada línea en una venta de ese cliente en esa
    sucursal: lo que el carrito del POS muestra antes de cobrar"""

    def __init__(
        self,
        products: ProductRepository,
        presentations: ProductPresentations,
        resolver: PriceResolver,
    ):
        self.products = products
        self.presentations = presentations
        self.resolver = resolver

    def _handle(self, query: ResolvePricesQuery) -> list[dict]:
        products = {
            p.require_id(): p
            for p in self.products.get_by_ids(i.product_id for i in query.items)
        }
        lines = []
        for item in query.items:
            product = products.get(item.product_id)
            if product is None:
                raise NotFoundError(f"Product with id {item.product_id} not found")
            presentation = self.presentations.resolve(product, item.presentation_id)
            lines.append(PriceLine(product, presentation, item.quantity))
        chain = self.resolver.chain(query.customer_id, query.branch_id)
        return [
            {
                "product_id": line.product.require_id(),
                "presentation_id": line.presentation.id,
                "quantity": line.quantity,
                "unit_price": resolved.unit_price,
                "price_list_id": resolved.price_list_id,
                "price_list_name": resolved.price_list_name,
                "min_quantity": resolved.min_quantity,
            }
            for line, resolved in zip(
                lines, self.resolver.prices(chain, lines), strict=True
            )
        ]
