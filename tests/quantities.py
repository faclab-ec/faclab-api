from collections.abc import Iterable, Mapping

from src.catalog.product.app.quantities import ProductQuantities
from src.shared.domain.quantity import (
    MAX_QUANTITY_DECIMALS,
    ensure_quantity_decimals,
    presentation_decimals,
)


class FakeProductQuantities(ProductQuantities):
    """ProductQuantities without repositories, for unit tests.

    `decimals` maps a product to the decimals of its unit and `units` a unit of
    measure to its decimals; anything else takes `default` (every decimal the
    database keeps, so a test that doesn't care about precision isn't bothered).
    """

    def __init__(
        self,
        decimals: Mapping[int, int] | None = None,
        units: Mapping[int, int] | None = None,
        default: int = MAX_QUANTITY_DECIMALS,
    ):
        self._decimals = dict(decimals or {})
        self._unit_decimals = dict(units or {})
        self._default = default

    def decimals(self, product_ids: Iterable[int]) -> dict[int, int]:
        return {
            product_id: self._decimals.get(product_id, self._default)
            for product_id in product_ids
        }

    def ensure_for_product(self, product, quantity) -> None:
        ensure_quantity_decimals(
            quantity, self._decimals.get(product.id, self._default), product.id
        )

    def ensure_for_presentation(self, product, factor, quantity) -> None:
        decimals = presentation_decimals(
            self._decimals.get(product.id, self._default), factor
        )
        ensure_quantity_decimals(quantity, decimals, product.id)

    def ensure_for_unit(self, unit_of_measure_id, quantities, product_id=None) -> None:
        decimals = (
            self._unit_decimals.get(unit_of_measure_id, self._default)
            if unit_of_measure_id
            else 0
        )
        for quantity in quantities:
            if quantity is not None:
                ensure_quantity_decimals(quantity, decimals, product_id)

    def describe(self, products: list[dict]) -> list[dict]:
        return [
            {
                **product,
                "unit_symbol": None,
                "quantity_decimals": self._unit_decimals.get(
                    product.get("unit_of_measure_id"), 0
                ),
            }
            for product in products
        ]
