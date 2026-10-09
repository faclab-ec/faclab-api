from unittest.mock import MagicMock

from src.catalog.product.app.product_names import with_product_names
from src.catalog.product.domain.entities import Product


def test_items_get_the_name_and_sku_of_their_product():
    product_repo = MagicMock()
    product_repo.get_by_ids.return_value = [
        Product(id=1, sku="LAP-1", name="Laptop"),
        Product(id=2, sku="MOU-2", name="Mouse"),
    ]
    items = [{"product_id": 1}, {"product_id": 2}, {"product_id": 1}, {"product_id": 9}]

    result = with_product_names(items, product_repo)

    assert [(i["product_name"], i["product_sku"]) for i in result] == [
        ("Laptop", "LAP-1"),
        ("Mouse", "MOU-2"),
        ("Laptop", "LAP-1"),
        (None, None),
    ]
    # One query for every item
    product_repo.get_by_ids.assert_called_once()
