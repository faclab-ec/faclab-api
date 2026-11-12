"""The real `InventoryCosts` over in-memory purchase prices, for unit tests"""

from decimal import Decimal
from unittest.mock import Mock

from src.inventory.stock.app.costs import InventoryCosts


def inventory_costs(
    purchase_prices: dict[int, Decimal] | None = None,
) -> InventoryCosts:
    """A product without a price here has none (an IN without cost into a
    location that never had it enters at 0)"""
    prices = purchase_prices or {}
    products = Mock()
    products.get_by_id.side_effect = lambda product_id: (
        Mock(purchase_price=prices[product_id]) if product_id in prices else None
    )
    return InventoryCosts(products)
