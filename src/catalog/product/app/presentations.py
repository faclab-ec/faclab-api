from collections.abc import Iterable
from typing import Any

from wireup import injectable

from src.catalog.product.app.repositories import (
    ProductPresentationRepository,
    ProductRepository,
)
from src.catalog.product.domain.entities import Product, ProductPresentation
from src.catalog.product.domain.exceptions import PresentationInactiveError
from src.catalog.uom.app.repositories import UnitOfMeasureRepository
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.quantity import DEFAULT_QUANTITY_DECIMALS, presentation_decimals


@injectable(lifetime="scoped")
class ProductPresentations:
    """Presentaciones de los productos (S5.2).

    Cada producto tiene una presentación base, su unidad de medida con factor 1,
    que lleva el código de barras del producto; los comandos de producto la crean
    y la mantienen. Una línea de venta, devolución o compra es de una presentación
    (la base si no se elige otra) y guarda su factor.
    """

    def __init__(
        self,
        presentations: ProductPresentationRepository,
        products: ProductRepository,
        units: UnitOfMeasureRepository,
    ):
        self.presentations = presentations
        self.products = products
        self.units = units

    def _unit_name(self, product: Product) -> str:
        unit = (
            self.units.get_by_id(product.unit_of_measure_id)
            if product.unit_of_measure_id
            else None
        )
        if unit is None:
            raise NotFoundError(
                f"Unit of measure with id {product.unit_of_measure_id} not found"
            )
        return unit.name

    def create_base(self, product: Product, barcode: str | None) -> ProductPresentation:
        """La presentación base de un producto nuevo: su unidad y su código de barras"""
        return self.presentations.create(
            ProductPresentation(
                product_id=product.require_id(),
                name=self._unit_name(product),
                barcode=barcode,
                is_base=True,
            )
        )

    def sync_base(self, product: Product, barcode: str | None) -> ProductPresentation:
        """Después de editar el producto: la base se llama como su unidad y lleva
        su código de barras"""
        base = self.presentations.base_of(product.require_id())
        if base is None:
            return self.create_base(product, barcode)
        name = self._unit_name(product)
        if (base.name, base.barcode) == (name, barcode):
            return base
        base.name = name
        base.barcode = barcode
        return self.presentations.update(base)

    def base_barcode(self, product_id: int) -> str | None:
        base = self.presentations.base_of(product_id)
        return base.barcode if base else None

    def resolve(
        self, product: Product, presentation_id: int | None
    ) -> ProductPresentation:
        """La presentación de una línea nueva: la indicada, del producto y activa,
        o la base"""
        if presentation_id is None:
            base = self.presentations.base_of(product.require_id())
            # Every product has one since S5.2; an unsaved stand-in keeps a
            # product loaded without it working in its unit
            return base or ProductPresentation(
                product_id=product.require_id(), name="", is_base=True
            )
        presentation = self.presentations.get_by_id(presentation_id)
        if presentation is None or presentation.product_id != product.id:
            raise NotFoundError(
                f"Presentation with id {presentation_id} of product {product.id} "
                "not found"
            )
        if not presentation.is_active:
            raise PresentationInactiveError(presentation_id)
        return presentation

    def by_barcode(self, barcode: str) -> tuple[Product, ProductPresentation] | None:
        """El producto activo y su presentación activa con ese código de barras"""
        presentation = self.presentations.by_barcode(barcode)
        if presentation is None or not presentation.is_active:
            return None
        product = self.products.get_by_id(presentation.product_id)
        if product is None or not product.is_active:
            return None
        return product, presentation

    def names(self, presentation_ids: Iterable[int | None]) -> dict[int, str]:
        """Nombre de cada presentación, para mostrar las líneas"""
        ids = {i for i in presentation_ids if i is not None}
        return {p.require_id(): p.name for p in self.presentations.get_by_ids(ids)}

    def describe(self, products: list[dict]) -> list[dict]:
        """Agrega a cada producto (ya descrito por `ProductQuantities.describe`)
        el código de barras de su base y sus presentaciones, con su precio y costo
        efectivos y los decimales que admite cada una"""
        by_product: dict[int, list[ProductPresentation]] = {}
        for presentation in self.presentations.for_products(p["id"] for p in products):
            by_product.setdefault(presentation.product_id, []).append(presentation)
        described = []
        for product in products:
            presentations = by_product.get(product["id"], [])
            base = next((p for p in presentations if p.is_base), None)
            described.append(
                {
                    **product,
                    "barcode": base.barcode if base else None,
                    "presentations": [
                        presentation_view(p, product) for p in presentations
                    ],
                }
            )
        return described


def presentation_view(
    presentation: ProductPresentation, product: dict[str, Any]
) -> dict[str, Any]:
    """Una presentación como la muestran las respuestas de producto"""
    unit_decimals = product.get("quantity_decimals", DEFAULT_QUANTITY_DECIMALS)
    return {
        **presentation.dict(),
        "effective_sale_price": presentation.effective_sale_price(
            product.get("sale_price")
        ),
        "effective_purchase_price": presentation.effective_purchase_price(
            product.get("purchase_price")
        ),
        "quantity_decimals": presentation_decimals(unit_decimals, presentation.factor),
    }
