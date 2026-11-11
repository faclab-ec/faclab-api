"""Price lists and their prices, audited (S5.3)"""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import Mock

import pytest

from src.catalog.product.domain.entities import Product, ProductPresentation
from src.pricing.app.commands.items import (
    CreatePriceListItemCommand,
    CreatePriceListItemCommandHandler,
    DeletePriceListItemCommand,
    DeletePriceListItemCommandHandler,
    UpdatePriceListItemCommand,
    UpdatePriceListItemCommandHandler,
)
from src.pricing.app.commands.price_lists import (
    CreatePriceListCommand,
    CreatePriceListCommandHandler,
    DeletePriceListCommand,
    DeletePriceListCommandHandler,
    UpdatePriceListCommand,
    UpdatePriceListCommandHandler,
    ensure_default_price_list,
)
from src.pricing.domain.entities import PriceList, PriceListItem
from src.pricing.domain.exceptions import (
    DefaultPriceListBasePriceError,
    DefaultPriceListLockedError,
)
from src.shared.app.audit import AuditAction
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.quantity import QuantityPrecisionError
from tests.audit import FakeAuditTrail
from tests.presentations import FakeProductPresentations
from tests.quantities import FakeProductQuantities

WHOLESALE = PriceList(id=1, name="Mayorista")
GENERAL = PriceList(id=2, name="General", is_default=True)
CEMENT = Product(id=100, name="Cemento", sku="FERR-003", sale_price=Decimal("9.50"))
BASE = ProductPresentation(id=10, product_id=100, name="Saco", is_base=True)
PALLET = ProductPresentation(
    id=11, product_id=100, name="Pallet x40", factor=Decimal(40)
)


def _echo(existing=None) -> Mock:
    repo = Mock()
    repo.get_by_id.return_value = existing
    repo.create.side_effect = lambda entity: replace(entity, id=entity.id or 9)
    repo.update.side_effect = lambda entity: entity
    return repo


def _catalog():
    products = Mock()
    products.get_by_id.side_effect = lambda i: CEMENT if i == 100 else None
    products.get_by_ids.return_value = [CEMENT]
    presentation_repo = Mock()
    presentation_repo.get_by_id.side_effect = {10: BASE, 11: PALLET}.get
    presentation_repo.get_by_ids.return_value = [BASE, PALLET]
    return products, presentation_repo


# Lists


def test_a_new_list_is_audited():
    audit = FakeAuditTrail()

    result = CreatePriceListCommandHandler(_echo(), audit).handle(
        CreatePriceListCommand(name="Mayorista", valid_from=date(2026, 11, 1))
    )

    (entry,) = audit.entries
    assert (entry.action, entry.resource_id) == (AuditAction.PRICE_LIST_CREATED, 9)
    assert entry.after == {
        "name": "Mayorista",
        "description": None,
        "is_active": True,
        "valid_from": date(2026, 11, 1),
        "valid_to": None,
    }
    assert result["is_default"] is False


def test_an_update_records_only_what_changed():
    audit = FakeAuditTrail()

    UpdatePriceListCommandHandler(_echo(replace(WHOLESALE)), audit).handle(
        UpdatePriceListCommand(price_list_id=1, name="Mayorista", is_active=False)
    )

    (entry,) = audit.entries
    assert (entry.before, entry.after) == ({"is_active": True}, {"is_active": False})


def test_the_general_list_cant_be_deactivated_nor_deleted():
    with pytest.raises(DefaultPriceListLockedError):
        UpdatePriceListCommandHandler(_echo(replace(GENERAL)), FakeAuditTrail()).handle(
            UpdatePriceListCommand(price_list_id=2, name="General", is_active=False)
        )
    with pytest.raises(DefaultPriceListLockedError):
        DeletePriceListCommandHandler(_echo(replace(GENERAL)), FakeAuditTrail()).handle(
            DeletePriceListCommand(price_list_id=2)
        )


def test_a_deleted_list_keeps_what_it_was():
    audit = FakeAuditTrail()
    lists = _echo(replace(WHOLESALE))

    DeletePriceListCommandHandler(lists, audit).handle(
        DeletePriceListCommand(price_list_id=1)
    )

    lists.delete.assert_called_once_with(1)
    (entry,) = audit.entries
    assert entry.action == AuditAction.PRICE_LIST_DELETED
    assert entry.before is not None and entry.before["name"] == "Mayorista"


def test_a_missing_list_is_not_found():
    with pytest.raises(NotFoundError):
        DeletePriceListCommandHandler(_echo(), FakeAuditTrail()).handle(
            DeletePriceListCommand(price_list_id=1)
        )


def test_a_company_gets_its_general_list_once():
    lists = _echo()
    lists.default.return_value = None

    created = ensure_default_price_list(lists)

    assert (created.name, created.is_default) == ("General", True)
    lists.default.return_value = created
    assert ensure_default_price_list(lists) is created
    lists.create.assert_called_once()


# Items


def _create_handler(price_list, audit, quantities=None):
    products, presentation_repo = _catalog()
    return CreatePriceListItemCommandHandler(
        _echo(price_list),
        _echo(),
        products,
        FakeProductPresentations([BASE, PALLET]),
        presentation_repo,
        quantities or FakeProductQuantities(),
        audit,
    )


def test_a_price_of_the_base_unit_is_audited_with_the_list_as_resource():
    audit = FakeAuditTrail()

    result = _create_handler(WHOLESALE, audit).handle(
        CreatePriceListItemCommand(
            price_list_id=1, product_id=100, presentation_id=10, price=Decimal("8.90")
        )
    )

    (entry,) = audit.entries
    assert (entry.action, entry.resource_id) == (
        AuditAction.PRICE_LIST_ITEM_CREATED,
        1,
    )
    assert entry.after == {
        "item_id": 9,
        "product_id": 100,
        "presentation_id": 10,
        "min_quantity": Decimal(0),
        "price": Decimal("8.90"),
    }
    assert result["product_name"] == "Cemento"


def test_a_tier_of_a_presentation_takes_its_decimals():
    with pytest.raises(QuantityPrecisionError):
        _create_handler(
            WHOLESALE, FakeAuditTrail(), FakeProductQuantities(decimals={100: 0})
        ).handle(
            CreatePriceListItemCommand(
                price_list_id=1,
                product_id=100,
                presentation_id=11,
                price=Decimal("350"),
                min_quantity=Decimal("2.5"),
            )
        )


def test_the_general_list_takes_only_tiers():
    with pytest.raises(DefaultPriceListBasePriceError):
        _create_handler(GENERAL, FakeAuditTrail()).handle(
            CreatePriceListItemCommand(
                price_list_id=2, product_id=100, price=Decimal("9")
            )
        )


def _item(**overrides: Any) -> PriceListItem:
    defaults: dict[str, Any] = {
        "id": 5,
        "price_list_id": 1,
        "product_id": 100,
        "presentation_id": 10,
        "price": Decimal("8.90"),
        "min_quantity": Decimal(0),
    }
    return PriceListItem(**{**defaults, **overrides})


def test_an_item_update_records_its_new_price():
    audit = FakeAuditTrail()
    products, presentation_repo = _catalog()

    UpdatePriceListItemCommandHandler(
        _echo(WHOLESALE),
        _echo(_item()),
        products,
        presentation_repo,
        FakeProductQuantities(),
        audit,
    ).handle(
        UpdatePriceListItemCommand(
            price_list_id=1, item_id=5, price=Decimal("8.70"), min_quantity=Decimal(0)
        )
    )

    (entry,) = audit.entries
    assert entry.action == AuditAction.PRICE_LIST_ITEM_UPDATED
    assert entry.before == {
        "item_id": 5,
        "product_id": 100,
        "presentation_id": 10,
        "price": Decimal("8.90"),
    }
    assert entry.after is not None and entry.after["price"] == Decimal("8.70")


def test_an_item_of_another_list_is_not_found():
    with pytest.raises(NotFoundError):
        DeletePriceListItemCommandHandler(
            _echo(_item(price_list_id=3)), FakeAuditTrail()
        ).handle(DeletePriceListItemCommand(price_list_id=1, item_id=5))


def test_a_deleted_item_is_audited():
    audit = FakeAuditTrail()
    items = _echo(_item())

    DeletePriceListItemCommandHandler(items, audit).handle(
        DeletePriceListItemCommand(price_list_id=1, item_id=5)
    )

    items.delete.assert_called_once_with(5)
    assert audit.actions == [AuditAction.PRICE_LIST_ITEM_DELETED]
