from src.catalog.product.app.repositories import ProductRepository


def with_product_names(
    items: list[dict], product_repo: ProductRepository
) -> list[dict]:
    """Agrega `product_name` y `product_sku` a cada ítem con una sola consulta.

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
    return items
