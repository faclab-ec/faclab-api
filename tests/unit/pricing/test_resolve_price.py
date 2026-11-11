"""The price a line takes from its chain of lists (S5.3)"""

from datetime import date
from decimal import Decimal

import pytest

from src.pricing.domain.entities import PriceList, PriceListItem
from src.pricing.domain.exceptions import (
    DefaultPriceListBasePriceError,
    DefaultPriceListLockedError,
    InvalidPriceListItemError,
    InvalidPriceListValidityError,
)
from src.pricing.domain.services import ListPrices, resolve_price

CEMENT = 1
UNIT, BOX = 10, 11  # presentations of the cement: its unit and a box of 25

WHOLESALE = PriceList(id=1, name="Mayorista")
BRANCH = PriceList(id=2, name="Sucursal Norte")
GENERAL = PriceList(id=3, name="General", is_default=True)


def _item(price_list: PriceList, presentation: int, price: str, from_qty="0"):
    return PriceListItem(
        price_list_id=price_list.require_id(),
        product_id=CEMENT,
        presentation_id=presentation,
        price=Decimal(price),
        min_quantity=Decimal(from_qty),
    )


def _resolve(chain, quantity, presentation=UNIT, factor="1", product_price="9.50"):
    return resolve_price(
        chain,
        presentation_id=presentation,
        factor=Decimal(factor),
        base_presentation_id=UNIT,
        quantity=Decimal(quantity),
        presentation_price=Decimal(product_price) if product_price else None,
    )


WHOLESALE_PRICES = ListPrices(
    WHOLESALE,
    [_item(WHOLESALE, UNIT, "8.90"), _item(WHOLESALE, UNIT, "8.50", from_qty="50")],
)


def test_a_wholesale_customer_gets_the_price_of_its_list():
    resolved = _resolve([WHOLESALE_PRICES, ListPrices(GENERAL, [])], "3")

    assert resolved.unit_price == Decimal("8.90")
    assert (resolved.price_list_id, resolved.price_list_name) == (1, "Mayorista")
    assert resolved.min_quantity == 0


@pytest.mark.parametrize(
    ("quantity", "price"), [("49", "8.90"), ("50", "8.50"), ("120", "8.50")]
)
def test_from_the_tier_quantity_the_volume_price_applies(quantity, price):
    resolved = _resolve([WHOLESALE_PRICES, ListPrices(GENERAL, [])], quantity)

    assert resolved.unit_price == Decimal(price)


def test_a_product_without_a_price_in_the_list_takes_the_general_one():
    resolved = _resolve([ListPrices(WHOLESALE, []), ListPrices(GENERAL, [])], "3")

    assert resolved.unit_price == Decimal("9.50")
    assert resolved.price_list_id is None


def test_the_general_list_adds_its_tiers_over_the_products_price():
    general = ListPrices(GENERAL, [_item(GENERAL, UNIT, "9.00", from_qty="10")])

    assert _resolve([general], "9").unit_price == Decimal("9.50")
    resolved = _resolve([general], "10")
    assert (resolved.unit_price, resolved.price_list_name) == (
        Decimal("9.00"),
        "General",
    )


def test_a_list_with_only_a_tier_lets_a_smaller_quantity_go_to_the_next_list():
    tier_only = ListPrices(WHOLESALE, [_item(WHOLESALE, UNIT, "8.00", from_qty="20")])
    branch = ListPrices(BRANCH, [_item(BRANCH, UNIT, "9.10")])

    assert _resolve([tier_only, branch], "5").unit_price == Decimal("9.10")
    assert _resolve([tier_only, branch], "20").unit_price == Decimal("8.00")


def test_a_box_without_its_own_item_takes_the_units_price_times_its_factor():
    resolved = _resolve([WHOLESALE_PRICES], "1", presentation=BOX, factor="25")

    assert resolved.unit_price == Decimal("222.50")  # 25 × 8.90


def test_the_units_tiers_compare_with_the_base_quantity_of_the_boxes():
    # 2 boxes are 50 units: the tier from 50 units applies
    resolved = _resolve([WHOLESALE_PRICES], "2", presentation=BOX, factor="25")

    assert resolved.unit_price == Decimal("212.50")  # 25 × 8.50


def test_the_boxs_own_item_comes_before_the_derived_price():
    prices = ListPrices(
        WHOLESALE, [*WHOLESALE_PRICES.items, _item(WHOLESALE, BOX, "200.00")]
    )

    assert _resolve([prices], "2", presentation=BOX, factor="25").unit_price == (
        Decimal("200.00")
    )


def test_without_any_price_the_line_has_none():
    resolved = _resolve([ListPrices(GENERAL, [])], "1", product_price=None)

    assert resolved.unit_price is None


# The list


def test_a_list_applies_only_while_active_and_within_its_dates():
    november = PriceList(
        name="Noviembre", valid_from=date(2026, 11, 1), valid_to=date(2026, 11, 30)
    )

    assert november.applies_on(date(2026, 11, 1))
    assert november.applies_on(date(2026, 11, 30))
    assert not november.applies_on(date(2026, 12, 1))
    assert not november.applies_on(date(2026, 10, 31))
    assert not PriceList(name="Vieja", is_active=False).applies_on(date(2026, 11, 1))


def test_a_list_cant_end_before_it_starts():
    with pytest.raises(InvalidPriceListValidityError):
        PriceList(name="Mal", valid_from=date(2026, 12, 1), valid_to=date(2026, 11, 1))


def test_the_general_list_is_always_active_and_cant_be_deleted():
    general = PriceList(id=3, name="General", is_default=True)

    with pytest.raises(DefaultPriceListLockedError):
        general.change(
            name="General",
            description=None,
            is_active=False,
            valid_from=None,
            valid_to=None,
        )
    with pytest.raises(DefaultPriceListLockedError):
        general.ensure_deletable()


def test_the_general_list_only_takes_tiers():
    with pytest.raises(DefaultPriceListBasePriceError):
        GENERAL.ensure_accepts(Decimal(0))
    GENERAL.ensure_accepts(Decimal(10))
    WHOLESALE.ensure_accepts(Decimal(0))


def test_an_item_cant_have_a_negative_price_or_quantity():
    with pytest.raises(InvalidPriceListItemError):
        _item(WHOLESALE, UNIT, "-1")
    with pytest.raises(InvalidPriceListItemError):
        _item(WHOLESALE, UNIT, "1", from_qty="-1")
