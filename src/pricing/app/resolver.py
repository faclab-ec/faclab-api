from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from wireup import injectable

from src.catalog.product.app.repositories import ProductPresentationRepository
from src.catalog.product.domain.entities import Product, ProductPresentation
from src.customers.app.repositories import CustomerRepository
from src.organization.app.repositories import BranchRepository
from src.pricing.app.repositories import PriceListItemRepository, PriceListRepository
from src.pricing.domain.entities import PriceList, PriceListItem
from src.pricing.domain.services import ListPrices, ResolvedPrice, resolve_price


@dataclass(frozen=True)
class PriceLine:
    """Una línea a la que se le busca precio: su producto, la presentación en que
    se vende y la cantidad en esa presentación"""

    product: Product
    presentation: ProductPresentation
    quantity: Decimal


@injectable(lifetime="scoped")
class PriceResolver:
    """El precio de las líneas de una venta según sus listas (S5.3).

    La cadena de una venta es la lista del cliente, la de su sucursal y la
    general, saltando las inactivas o fuera de vigencia. Lee las listas que
    asignan clientes y sucursales; lo usan el POS (venta rápida, agregar y
    actualizar ítems) y la resolución que consulta la web.
    """

    def __init__(
        self,
        lists: PriceListRepository,
        items: PriceListItemRepository,
        customers: CustomerRepository,
        branches: BranchRepository,
        presentations: ProductPresentationRepository,
    ):
        self.lists = lists
        self.items = items
        self.customers = customers
        self.branches = branches
        self.presentations = presentations

    def chain(
        self,
        customer_id: int | None,
        branch_id: int | None,
        day: date | None = None,
    ) -> list[PriceList]:
        """Las listas que rigen una venta de ese cliente en esa sucursal, en orden"""
        day = day or date.today()
        assigned: list[int] = []
        customer = self.customers.get_by_id(customer_id) if customer_id else None
        if customer is not None and customer.price_list_id is not None:
            assigned.append(customer.price_list_id)
        branch = self.branches.get_by_id(branch_id) if branch_id else None
        if branch is not None and branch.price_list_id is not None:
            assigned.append(branch.price_list_id)
        by_id = {p.require_id(): p for p in self.lists.get_by_ids(assigned)}
        chain = [by_id[i] for i in assigned if i in by_id and by_id[i].applies_on(day)]
        default = self.lists.default()
        if default is not None:
            chain.append(default)
        unique: dict[int, PriceList] = {}
        for price_list in chain:
            unique.setdefault(price_list.require_id(), price_list)
        return list(unique.values())

    def prices(
        self, chain: Sequence[PriceList], lines: Sequence[PriceLine]
    ) -> list[ResolvedPrice]:
        """El precio de cada línea, con una consulta de ítems para todas"""
        product_ids = {line.product.require_id() for line in lines}
        by_list_and_product: dict[tuple[int, int], list[PriceListItem]] = {}
        for item in self.items.for_products(
            (p.require_id() for p in chain), product_ids
        ):
            key = (item.price_list_id, item.product_id)
            by_list_and_product.setdefault(key, []).append(item)
        bases = self._bases(lines)
        resolved = []
        for line in lines:
            product_id = line.product.require_id()
            resolved.append(
                resolve_price(
                    [
                        ListPrices(
                            price_list,
                            by_list_and_product.get(
                                (price_list.require_id(), product_id), []
                            ),
                        )
                        for price_list in chain
                    ],
                    presentation_id=line.presentation.id,
                    factor=line.presentation.factor,
                    base_presentation_id=bases.get(product_id),
                    quantity=line.quantity,
                    presentation_price=line.presentation.effective_sale_price(
                        line.product.sale_price
                    ),
                )
            )
        return resolved

    def price(
        self,
        chain: Sequence[PriceList],
        product: Product,
        presentation: ProductPresentation,
        quantity: Decimal,
    ) -> ResolvedPrice:
        [resolved] = self.prices(chain, [PriceLine(product, presentation, quantity)])
        return resolved

    def _bases(self, lines: Sequence[PriceLine]) -> dict[int, int | None]:
        """La presentación base del producto de cada línea"""
        bases: dict[int, int | None] = {}
        others = set()
        for line in lines:
            if line.presentation.is_base:
                bases[line.product.require_id()] = line.presentation.id
            else:
                others.add(line.product.require_id())
        others -= set(bases)
        for presentation in self.presentations.for_products(others):
            if presentation.is_base:
                bases[presentation.product_id] = presentation.id
        return bases
