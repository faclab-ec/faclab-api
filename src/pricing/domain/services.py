"""Resolución del precio de una línea (S5.3).

Una venta recorre su cadena de listas en orden: la del cliente, la de su
sucursal y la general. La primera lista con un precio para la línea gana; sin
ninguno, la línea toma el precio de su presentación (el propio o factor × el del
producto).

Dentro de una lista, una presentación P vendida en cantidad q toma:

1. el ítem de P con la mayor cantidad mínima que no supere q;
2. si P no es la base y la lista no tiene ítem de P, el de la unidad base con la
   mayor cantidad mínima que no supere q × factor, multiplicado por el factor
   (como el precio de una presentación sin precio propio, S5.2).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from src.catalog.product.domain.entities import PRICE_SCALE
from src.pricing.domain.entities import PriceList, PriceListItem


@dataclass(frozen=True)
class ResolvedPrice:
    """El precio de una línea y la lista que lo dio (ninguna: el del producto)"""

    unit_price: Decimal | None
    price_list_id: int | None = None
    price_list_name: str | None = None
    # Desde qué cantidad rige el ítem que lo dio, en su presentación
    min_quantity: Decimal | None = None


@dataclass(frozen=True)
class ListPrices:
    """Una lista de la cadena con sus ítems del producto de la línea"""

    price_list: PriceList
    items: Sequence[PriceListItem]


def _best(
    items: Iterable[PriceListItem], presentation_id: int, quantity: Decimal
) -> PriceListItem | None:
    best: PriceListItem | None = None
    for item in items:
        if item.presentation_id != presentation_id or item.min_quantity > quantity:
            continue
        if best is None or item.min_quantity > best.min_quantity:
            best = item
    return best


def price_in_list(
    items: Sequence[PriceListItem],
    *,
    presentation_id: int | None,
    factor: Decimal,
    base_presentation_id: int | None,
    quantity: Decimal,
) -> tuple[Decimal, PriceListItem] | None:
    """El precio que una lista da a una línea, o None si no tiene ninguno"""
    if presentation_id is not None:
        item = _best(items, presentation_id, quantity)
        if item is not None:
            return Decimal(str(item.price)), item
    if base_presentation_id is None or presentation_id == base_presentation_id:
        return None
    item = _best(items, base_presentation_id, quantity * factor)
    if item is None:
        return None
    return (Decimal(str(item.price)) * factor).quantize(PRICE_SCALE), item


def resolve_price(
    chain: Sequence[ListPrices],
    *,
    presentation_id: int | None,
    factor: Decimal,
    base_presentation_id: int | None,
    quantity: Decimal,
    presentation_price: Decimal | None,
) -> ResolvedPrice:
    """El precio de una línea: el de la primera lista de la cadena que tenga
    uno, o `presentation_price` (el de la presentación, la lista general)"""
    for prices in chain:
        found = price_in_list(
            prices.items,
            presentation_id=presentation_id,
            factor=factor,
            base_presentation_id=base_presentation_id,
            quantity=quantity,
        )
        if found is not None:
            price, item = found
            return ResolvedPrice(
                unit_price=price,
                price_list_id=prices.price_list.id,
                price_list_name=prices.price_list.name,
                min_quantity=item.min_quantity,
            )
    return ResolvedPrice(unit_price=presentation_price)
