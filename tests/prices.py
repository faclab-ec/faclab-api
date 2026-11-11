"""The real PriceResolver over in-memory data, for unit tests (S5.3)"""

from collections.abc import Iterable, Mapping
from types import SimpleNamespace
from unittest.mock import Mock

from src.catalog.product.domain.entities import ProductPresentation
from src.pricing.app.resolver import PriceResolver
from src.pricing.domain.entities import PriceList, PriceListItem


def price_resolver(
    lists: Iterable[PriceList] = (),
    items: Iterable[PriceListItem] = (),
    customer_lists: Mapping[int, int] | None = None,
    branch_lists: Mapping[int, int] | None = None,
    bases: Mapping[int, int] | None = None,
) -> PriceResolver:
    """A resolver whose repositories hold `lists` and `items`.

    `customer_lists` and `branch_lists` give a customer's or a branch's list,
    `bases` each product's base presentation (for a line in another one).
    Without lists every line takes its presentation's price, as a company
    whose general list has no tiers.
    """
    lists, items = list(lists), list(items)
    by_customer = dict(customer_lists or {})
    by_branch = dict(branch_lists or {})
    base_of = dict(bases or {})

    list_repo = Mock()
    list_repo.get_by_ids.side_effect = lambda ids: [
        p for p in lists if p.id in set(ids)
    ]
    list_repo.default.return_value = next((p for p in lists if p.is_default), None)

    item_repo = Mock()

    def for_products(list_ids, product_ids):
        list_ids, product_ids = set(list_ids), set(product_ids)
        return [
            i
            for i in items
            if i.price_list_id in list_ids and i.product_id in product_ids
        ]

    item_repo.for_products.side_effect = for_products

    customers = Mock()
    customers.get_by_id.side_effect = lambda i: SimpleNamespace(
        id=i, price_list_id=by_customer.get(i)
    )
    branches = Mock()
    branches.get_by_id.side_effect = lambda i: SimpleNamespace(
        id=i, price_list_id=by_branch.get(i)
    )
    presentations = Mock()
    presentations.for_products.side_effect = lambda ids: [
        ProductPresentation(id=base_of[p], product_id=p, name="", is_base=True)
        for p in set(ids)
        if p in base_of
    ]
    return PriceResolver(list_repo, item_repo, customers, branches, presentations)
