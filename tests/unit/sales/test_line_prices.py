"""A POS line takes the price of its list; another one needs a reason (S5.3)"""

from dataclasses import replace
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.catalog.product.domain.entities import Product, ProductPresentation
from src.pricing.domain.entities import PriceList, PriceListItem
from src.sales.app.commands.add_sale_item import (
    AddSaleItemCommand,
    AddSaleItemCommandHandler,
)
from src.sales.app.commands.update_sale_item import (
    UpdateSaleItemCommand,
    UpdateSaleItemCommandHandler,
)
from src.sales.domain.entities import Sale, SaleItem, SaleStatus
from src.sales.domain.exceptions import (
    OverrideReasonRequiredError,
    ProductWithoutPriceError,
)
from src.sales.domain.pricing import line_price
from src.shared.app.audit import AuditAction
from tests.audit import FakeAuditTrail
from tests.presentations import FakeProductPresentations
from tests.prices import price_resolver
from tests.quantities import FakeProductQuantities

WHOLESALE_CUSTOMER, BRANCH = 10, 3
CEMENT = Product(id=100, name="Cemento", sku="FERR-003", sale_price=Decimal("9.50"))
BASE = ProductPresentation(id=50, product_id=100, name="Saco", is_base=True)
WHOLESALE = PriceList(id=1, name="Mayorista")
GENERAL = PriceList(id=2, name="General", is_default=True)


def _resolver():
    """The wholesale customer pays 8.90, 8.50 from 50 bags; everyone else 9.50
    and 9.00 from 10 bags"""
    return price_resolver(
        lists=[WHOLESALE, GENERAL],
        items=[
            PriceListItem(
                price_list_id=1,
                product_id=100,
                presentation_id=50,
                price=Decimal("8.90"),
            ),
            PriceListItem(
                price_list_id=1,
                product_id=100,
                presentation_id=50,
                price=Decimal("8.50"),
                min_quantity=Decimal(50),
            ),
            PriceListItem(
                price_list_id=2,
                product_id=100,
                presentation_id=50,
                price=Decimal("9.00"),
                min_quantity=Decimal(10),
            ),
        ],
        customer_lists={WHOLESALE_CUSTOMER: 1},
        bases={100: 50},
    )


def _sale(customer_id=WHOLESALE_CUSTOMER) -> Sale:
    return Sale(
        id=1,
        customer_id=customer_id,
        is_final_consumer=customer_id is None,
        branch_id=BRANCH,
        status=SaleStatus.DRAFT,
    )


def _add(command: AddSaleItemCommand, sale: Sale | None = None, audit=None):
    sale_repo = MagicMock()
    sale_repo.get_by_id.return_value = sale or _sale()
    items = MagicMock()
    items.create.side_effect = lambda item: replace(item, id=7)
    items.filter_by.return_value = []
    products = MagicMock()
    products.get_by_id.return_value = CEMENT
    handler = AddSaleItemCommandHandler(
        sale_repo,
        items,
        products,
        MagicMock(),
        FakeProductQuantities(),
        FakeProductPresentations([BASE]),
        _resolver(),
        audit or FakeAuditTrail(),
    )
    return handler.handle(command)


def _line(quantity, **overrides) -> AddSaleItemCommand:
    return AddSaleItemCommand(
        sale_id=1,
        product_id=100,
        quantity=Decimal(quantity),
        presentation_id=50,
        **overrides,
    )


def test_a_wholesale_customer_gets_the_price_of_its_list():
    result = _add(_line(3))

    assert result["unit_price"] == Decimal("8.90")
    assert result["price_override"] is None


def test_above_the_tier_the_line_takes_the_volume_price():
    assert _add(_line(60))["unit_price"] == Decimal("8.50")


def test_a_final_consumer_takes_the_general_price_and_its_tier():
    assert _add(_line(3), _sale(customer_id=None))["unit_price"] == Decimal("9.50")
    assert _add(_line(12), _sale(customer_id=None))["unit_price"] == Decimal("9.00")


def test_the_list_price_sent_by_the_client_is_not_an_override():
    audit = FakeAuditTrail()

    result = _add(_line(3, unit_price=Decimal("8.90")), audit=audit)

    assert result["price_override"] is None
    assert audit.entries == []


def test_another_price_needs_a_reason():
    with pytest.raises(OverrideReasonRequiredError):
        _add(_line(3, unit_price=Decimal("8.00")))


def test_another_price_with_its_reason_is_recorded_and_audited():
    audit = FakeAuditTrail()

    result = _add(
        _line(3, unit_price=Decimal("8.00"), override_reason="Cliente frecuente"),
        audit=audit,
    )

    assert (result["unit_price"], result["price_override"]) == (
        Decimal("8.00"),
        Decimal("8.00"),
    )
    assert result["override_reason"] == "Cliente frecuente"
    (entry,) = audit.entries
    assert entry.action == AuditAction.SALE_PRICE_OVERRIDDEN
    assert entry.before == {"unit_price": Decimal("8.90")}
    assert entry.branch_id == BRANCH


def test_a_line_without_any_price_needs_one():
    with pytest.raises(ProductWithoutPriceError):
        line_price(100, None, None, None)
    # Without a list price any price goes, without a reason
    assert line_price(100, None, Decimal("3"), None) == (Decimal("3"), False)


def _update(item: SaleItem, quantity) -> SaleItem:
    sale_repo = MagicMock()
    sale_repo.get_by_id.return_value = _sale()
    items = MagicMock()
    items.get_by_id.return_value = item
    items.filter_by.return_value = [item]
    products = MagicMock()
    products.get_by_id.return_value = CEMENT
    presentation_repo = MagicMock()
    presentation_repo.get_by_id.return_value = BASE
    UpdateSaleItemCommandHandler(
        sale_repo,
        items,
        FakeProductQuantities(),
        products,
        presentation_repo,
        FakeProductPresentations([BASE]),
        _resolver(),
    ).handle(
        UpdateSaleItemCommand(sale_id=1, sale_item_id=7, quantity=Decimal(quantity))
    )
    return item


def _item(**overrides: Any) -> SaleItem:
    defaults: dict[str, Any] = {
        "id": 7,
        "sale_id": 1,
        "product_id": 100,
        "quantity": Decimal(3),
        "unit_price": Decimal("8.90"),
        "presentation_id": 50,
    }
    return SaleItem(**{**defaults, **overrides})


def test_a_new_quantity_reaches_the_volume_tier():
    item = _update(_item(), 60)

    assert (item.quantity, item.unit_price) == (Decimal(60), Decimal("8.50"))


def test_an_overridden_line_keeps_its_price():
    item = _update(
        _item(
            unit_price=Decimal("8.00"),
            price_override=Decimal("8.00"),
            override_reason="Cliente frecuente",
        ),
        60,
    )

    assert item.unit_price == Decimal("8.00")
