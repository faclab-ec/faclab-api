from collections.abc import Iterable

from src.catalog.product.app.presentations import (
    ProductPresentations,
    presentation_view,
)
from src.catalog.product.domain.entities import Product, ProductPresentation
from src.catalog.product.domain.exceptions import PresentationInactiveError
from src.shared.domain.exceptions import NotFoundError


class FakeProductPresentations(ProductPresentations):
    """ProductPresentations without repositories, for unit tests.

    Every product sells in its base unit (an unsaved base, factor 1) unless
    `presentations` lists others. `barcodes` keeps each product's base barcode,
    as the commands of products leave it.
    """

    def __init__(self, presentations: Iterable[ProductPresentation] = ()):
        self._presentations = {p.id: p for p in presentations}
        self.barcodes: dict[int | None, str | None] = {}

    def create_base(self, product: Product, barcode: str | None) -> ProductPresentation:
        self.barcodes[product.id] = barcode
        return self._base(product, barcode)

    def sync_base(self, product: Product, barcode: str | None) -> ProductPresentation:
        return self.create_base(product, barcode)

    def base_barcode(self, product_id: int) -> str | None:
        return self.barcodes.get(product_id)

    def resolve(
        self, product: Product, presentation_id: int | None
    ) -> ProductPresentation:
        if presentation_id is None:
            return self._base(product, self.barcodes.get(product.id))
        presentation = self._presentations.get(presentation_id)
        if presentation is None or presentation.product_id != product.id:
            raise NotFoundError(f"Presentation with id {presentation_id} not found")
        if not presentation.is_active:
            raise PresentationInactiveError(presentation_id)
        return presentation

    def by_barcode(self, barcode: str) -> tuple[Product, ProductPresentation] | None:
        return None

    def names(self, presentation_ids: Iterable[int | None]) -> dict[int, str]:
        return {
            i: self._presentations[i].name
            for i in presentation_ids
            if i is not None and i in self._presentations
        }

    def describe(self, products: list[dict]) -> list[dict]:
        return [
            {
                **product,
                "barcode": self.barcodes.get(product["id"]),
                "presentations": [
                    presentation_view(p, product)
                    for p in self._presentations.values()
                    if p.product_id == product["id"]
                ],
            }
            for product in products
        ]

    @staticmethod
    def _base(product: Product, barcode: str | None) -> ProductPresentation:
        return ProductPresentation(
            product_id=product.require_id(),
            name="Unidad",
            barcode=barcode,
            is_base=True,
        )
