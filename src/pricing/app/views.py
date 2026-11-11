from collections.abc import Sequence

from src.catalog.product.app.repositories import (
    ProductPresentationRepository,
    ProductRepository,
)
from src.pricing.domain.entities import PriceListItem


def item_views(
    items: Sequence[PriceListItem],
    products: ProductRepository,
    presentations: ProductPresentationRepository,
) -> list[dict]:
    """Los ítems como los muestran las respuestas: con el nombre y el SKU de su
    producto y el nombre y el factor de su presentación"""
    by_product = {p.id: p for p in products.get_by_ids(i.product_id for i in items)}
    by_presentation = {
        p.id: p for p in presentations.get_by_ids(i.presentation_id for i in items)
    }
    views = []
    for item in items:
        product = by_product.get(item.product_id)
        presentation = by_presentation.get(item.presentation_id)
        views.append(
            {
                **item.dict(),
                "product_name": product.name if product else None,
                "product_sku": product.sku if product else None,
                "presentation_name": presentation.name if presentation else None,
                "unit_factor": presentation.factor if presentation else None,
                "is_base_presentation": bool(presentation and presentation.is_base),
            }
        )
    return views
