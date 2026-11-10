"""The chain of lists of a sale and the price of its lines (S5.3)"""

from datetime import date
from decimal import Decimal

from src.catalog.product.domain.entities import Product, ProductPresentation
from src.pricing.app.resolver import PriceLine
from src.pricing.domain.entities import PriceList, PriceListItem
from tests.prices import price_resolver

CUSTOMER, BRANCH = 5, 7
WHOLESALE = PriceList(id=1, name="Mayorista")
NORTH = PriceList(id=2, name="Norte")
GENERAL = PriceList(id=3, name="General", is_default=True)
OLD = PriceList(id=4, name="Vieja", is_active=False)

CEMENT = Product(id=100, name="Cemento", sku="FERR-003", sale_price=Decimal("9.50"))
UNIT = ProductPresentation(id=10, product_id=100, name="Saco", is_base=True)
BOX = ProductPresentation(id=11, product_id=100, name="Pallet x40", factor=Decimal(40))


def _item(price_list, price, presentation=UNIT, from_qty="0"):
    return PriceListItem(
        price_list_id=price_list.id,
        product_id=CEMENT.require_id(),
        presentation_id=presentation.require_id(),
        price=Decimal(price),
        min_quantity=Decimal(from_qty),
    )


def test_the_chain_is_the_customers_list_the_branchs_and_the_general_one():
    resolver = price_resolver(
        lists=[WHOLESALE, NORTH, GENERAL],
        customer_lists={CUSTOMER: 1},
        branch_lists={BRANCH: 2},
    )

    assert resolver.chain(CUSTOMER, BRANCH) == [WHOLESALE, NORTH, GENERAL]
    assert resolver.chain(None, BRANCH) == [NORTH, GENERAL]
    assert resolver.chain(None, None) == [GENERAL]


def test_an_inactive_or_expired_list_is_skipped():
    expired = PriceList(id=5, name="Octubre", valid_to=date(2026, 10, 31))
    resolver = price_resolver(
        lists=[OLD, expired, GENERAL],
        customer_lists={CUSTOMER: 4},
        branch_lists={BRANCH: 5},
    )

    assert resolver.chain(CUSTOMER, BRANCH, day=date(2026, 11, 10)) == [GENERAL]


def test_the_same_list_on_customer_and_branch_appears_once():
    resolver = price_resolver(
        lists=[WHOLESALE, GENERAL],
        customer_lists={CUSTOMER: 1},
        branch_lists={BRANCH: 1},
    )

    assert resolver.chain(CUSTOMER, BRANCH) == [WHOLESALE, GENERAL]


def test_each_line_takes_the_first_list_with_a_price_for_it():
    resolver = price_resolver(
        lists=[WHOLESALE, GENERAL],
        items=[_item(WHOLESALE, "8.90"), _item(GENERAL, "9.00", from_qty="10")],
        customer_lists={CUSTOMER: 1},
        bases={100: 10},
    )
    chain = resolver.chain(CUSTOMER, None)

    unit, pallet = resolver.prices(
        chain,
        [
            PriceLine(CEMENT, UNIT, Decimal(3)),
            PriceLine(CEMENT, BOX, Decimal(1)),
        ],
    )

    assert (unit.unit_price, unit.price_list_name) == (Decimal("8.90"), "Mayorista")
    # The pallet without its own item: 40 × the unit's price in the list
    assert pallet.unit_price == Decimal("356.00")


def test_without_lists_a_line_takes_its_presentations_price():
    resolver = price_resolver()

    resolved = resolver.price([], CEMENT, BOX, Decimal(1))

    assert resolved.unit_price == Decimal("380.00")  # 40 × 9.50
    assert resolved.price_list_id is None
