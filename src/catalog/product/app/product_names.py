from src.catalog.product.app.repositories import (
    ProductPresentationRepository,
    ProductRepository,
)


def with_product_names(
    items: list[dict],
    product_repo: ProductRepository,
    presentations: ProductPresentationRepository | None = None,
) -> list[dict]:
    """Agrega `product_name` y `product_sku` a cada ítem con una sola consulta y,
    con `presentations`, el `presentation_name` de los que tienen presentación
    (S5.2).

    Así la web muestra los ítems de una orden, venta, ajuste o transferencia sin
    cargar el catálogo completo.
    """
    products = {
        product.id: product
        for product in product_repo.get_by_ids(item["product_id"] for item in items)
    }
    for item in items:
        product = products.get(item["product_id"])
        item["product_name"] = product.name if product else None
        item["product_sku"] = product.sku if product else None
    if presentations is not None:
        names = {
            presentation.id: presentation.name
            for presentation in presentations.get_by_ids(
                item["presentation_id"]
                for item in items
                if item.get("presentation_id") is not None
            )
        }
        for item in items:
            item["presentation_name"] = names.get(item.get("presentation_id"))
    return items
