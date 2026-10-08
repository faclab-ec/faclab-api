from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.sales.app.commands.update_sale_item import (
    UpdateSaleItemCommand,
    UpdateSaleItemCommandHandler,
)
from src.sales.domain.entities import Sale, SaleItem, SaleStatus
from src.sales.domain.exceptions import InvalidSaleStatusError
from src.shared.domain.exceptions import DomainError, NotFoundError


def _make_sale(**overrides) -> Sale:
    defaults: dict[str, Any] = {
        "id": 1,
        "customer_id": 10,
        "status": SaleStatus.DRAFT,
        "subtotal": Decimal("0"),
        "total": Decimal("0"),
    }
    defaults.update(overrides)
    return Sale(**defaults)


def _make_sale_item(**overrides) -> SaleItem:
    defaults: dict[str, Any] = {
        "id": 1,
        "sale_id": 1,
        "product_id": 100,
        "quantity": 10,
        "unit_price": Decimal("100.00"),
        "discount": Decimal("0"),
    }
    defaults.update(overrides)
    return SaleItem(**defaults)


def _mock_repo(entity=None, entities=None):
    repo = MagicMock()
    if entity is not None:
        repo.create.return_value = entity
        repo.update.return_value = entity
        repo.get_by_id.return_value = entity
        repo.first.return_value = entity
    if entities is not None:
        repo.filter_by.return_value = entities
        repo.get_all.return_value = entities
    return repo


def test_update_sale_item_quantity():
    """Test actualizar cantidad de un item"""
    sale = _make_sale()
    item = _make_sale_item()
    sale_repo = _mock_repo(entity=sale)
    sale_item_repo = _mock_repo(entity=item, entities=[item])
    handler = UpdateSaleItemCommandHandler(sale_repo, sale_item_repo)

    command = UpdateSaleItemCommand(sale_id=1, sale_item_id=1, quantity=5)
    result = handler.handle(command)

    assert item.quantity == 5
    sale_item_repo.update.assert_called_once_with(item)
    sale_repo.update.assert_called_once()
    assert "subtotal" in result


def test_update_sale_item_discount():
    """Test actualizar descuento de un item"""
    sale = _make_sale()
    item = _make_sale_item()
    sale_repo = _mock_repo(entity=sale)
    sale_item_repo = _mock_repo(entity=item, entities=[item])
    handler = UpdateSaleItemCommandHandler(sale_repo, sale_item_repo)

    command = UpdateSaleItemCommand(sale_id=1, sale_item_id=1, discount=Decimal("10"))
    result = handler.handle(command)

    assert item.discount == Decimal("10")
    sale_item_repo.update.assert_called_once_with(item)
    assert "subtotal" in result


def test_update_sale_item_sale_not_found():
    """Test error cuando la venta no existe"""
    sale_repo = _mock_repo()
    sale_repo.get_by_id.return_value = None
    sale_item_repo = _mock_repo()
    handler = UpdateSaleItemCommandHandler(sale_repo, sale_item_repo)

    with pytest.raises(NotFoundError):
        handler.handle(UpdateSaleItemCommand(sale_id=999, sale_item_id=1))


def test_update_sale_item_item_not_found():
    """Test error cuando el item no existe"""
    sale = _make_sale()
    sale_repo = _mock_repo(entity=sale)
    sale_item_repo = _mock_repo()
    sale_item_repo.get_by_id.return_value = None
    handler = UpdateSaleItemCommandHandler(sale_repo, sale_item_repo)

    with pytest.raises(NotFoundError):
        handler.handle(UpdateSaleItemCommand(sale_id=1, sale_item_id=999))


def test_update_sale_item_not_draft():
    """Test error cuando la venta no esta en DRAFT"""
    sale = _make_sale(status=SaleStatus.CONFIRMED)
    sale_repo = _mock_repo(entity=sale)
    sale_item_repo = _mock_repo()
    handler = UpdateSaleItemCommandHandler(sale_repo, sale_item_repo)

    with pytest.raises(InvalidSaleStatusError):
        handler.handle(UpdateSaleItemCommand(sale_id=1, sale_item_id=1, quantity=5))


def test_update_sale_item_wrong_sale():
    """Test error cuando el item no pertenece a la venta"""
    sale = _make_sale()
    item = _make_sale_item(sale_id=999)
    sale_repo = _mock_repo(entity=sale)
    sale_item_repo = _mock_repo(entity=item)
    handler = UpdateSaleItemCommandHandler(sale_repo, sale_item_repo)

    with pytest.raises(DomainError):
        handler.handle(UpdateSaleItemCommand(sale_id=1, sale_item_id=1, quantity=5))
