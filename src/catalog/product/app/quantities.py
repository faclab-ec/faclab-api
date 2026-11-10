from collections.abc import Iterable
from decimal import Decimal

from wireup import injectable

from src.catalog.product.app.repositories import ProductRepository
from src.catalog.product.domain.entities import Product
from src.catalog.uom.app.repositories import UnitOfMeasureRepository
from src.catalog.uom.domain.entities import UnitOfMeasure
from src.shared.domain.quantity import (
    DEFAULT_QUANTITY_DECIMALS,
    ensure_quantity_decimals,
)


@injectable(lifetime="scoped")
class ProductQuantities:
    """Decimales que admite la cantidad de cada producto (S5.1).

    Los define su unidad de medida; un producto sin unidad solo acepta enteros.
    Se valida cuando alguien escribe una cantidad (una línea de venta, de compra,
    de ajuste, un movimiento manual), no al leer lo ya guardado: bajar los
    decimales de una unidad no invalida el stock ni los documentos anteriores.
    """

    def __init__(self, products: ProductRepository, units: UnitOfMeasureRepository):
        self.products = products
        self.units = units

    def _units(self, products: Iterable[Product]) -> dict[int, UnitOfMeasure]:
        unit_ids = {p.unit_of_measure_id for p in products if p.unit_of_measure_id}
        return {unit.require_id(): unit for unit in self.units.get_by_ids(unit_ids)}

    def decimals(self, product_ids: Iterable[int]) -> dict[int, int]:
        """Decimales por producto, con una consulta de productos y otra de unidades.
        Los productos que no existen no aparecen."""
        products = self.products.get_by_ids(product_ids)
        units = self._units(products)
        return {
            product.require_id(): _decimals(product.unit_of_measure_id, units)
            for product in products
        }

    def ensure(self, lines: Iterable[tuple[int, Decimal | int]]) -> None:
        """Rechaza la primera cantidad con más decimales de los que admite su
        producto. Un producto que no existe se salta: su handler responde 404."""
        lines = list(lines)
        decimals = self.decimals(product_id for product_id, _ in lines)
        for product_id, quantity in lines:
            if product_id in decimals:
                ensure_quantity_decimals(quantity, decimals[product_id], product_id)

    def ensure_for_product(self, product: Product, quantity: Decimal | int) -> None:
        """Una cantidad de un producto ya cargado: solo consulta su unidad"""
        self.ensure_for_unit(
            product.unit_of_measure_id, [quantity], product_id=product.id
        )

    def ensure_for_unit(
        self,
        unit_of_measure_id: int | None,
        quantities: Iterable[Decimal | int | None],
        product_id: int | None = None,
    ) -> None:
        """Cantidades en una unidad, p. ej. los umbrales de stock de un producto
        con la unidad que se le asigna"""
        units = (
            {u.require_id(): u for u in self.units.get_by_ids([unit_of_measure_id])}
            if unit_of_measure_id
            else {}
        )
        decimals = _decimals(unit_of_measure_id, units)
        for quantity in quantities:
            if quantity is not None:
                ensure_quantity_decimals(quantity, decimals, product_id)

    def describe(self, products: list[dict]) -> list[dict]:
        """Agrega a cada producto el símbolo de su unidad y sus decimales, para
        que el POS y los formularios sepan qué cantidades aceptar"""
        unit_ids = {
            p["unit_of_measure_id"] for p in products if p["unit_of_measure_id"]
        }
        units = {unit.require_id(): unit for unit in self.units.get_by_ids(unit_ids)}
        described = []
        for product in products:
            unit = units.get(product["unit_of_measure_id"])
            described.append(
                {
                    **product,
                    "unit_symbol": unit.symbol if unit else None,
                    "quantity_decimals": _decimals(
                        product["unit_of_measure_id"], units
                    ),
                }
            )
        return described


def _decimals(unit_of_measure_id: int | None, units: dict[int, UnitOfMeasure]) -> int:
    unit = units.get(unit_of_measure_id) if unit_of_measure_id else None
    return unit.decimals if unit else DEFAULT_QUANTITY_DECIMALS
