from decimal import Decimal

from wireup import injectable

from src.catalog.product.app.repositories import ProductRepository
from src.inventory.stock.domain.entities import Stock
from src.shared.domain.money import round_cost


@injectable(lifetime="scoped")
class InventoryCosts:
    """The cost an IN enters at (S5.6), per base unit. Every IN recalculates the
    weighted average of its location with it; every OUT takes that average.

    Documents that know their cost pass it (a purchase line, the source of a
    transfer, the sale a cancellation or refund reverses). Without it the units
    enter at the location's average, which then doesn't change; a location that
    never had the product takes its purchase price, or 0."""

    def __init__(self, products: ProductRepository):
        self.products = products

    def entry_cost(
        self, product_id: int, stock: Stock | None, unit_cost: Decimal | None = None
    ) -> Decimal:
        if unit_cost is not None:
            return round_cost(unit_cost)
        if stock is not None:
            return stock.average_cost
        product = self.products.get_by_id(product_id)
        if product is None or product.purchase_price is None:
            return Decimal(0)
        return round_cost(product.purchase_price)

    @staticmethod
    def exit_cost(stock: Stock | None) -> Decimal:
        """An OUT leaves at the average of the location it takes from"""
        return stock.average_cost if stock is not None else Decimal(0)
