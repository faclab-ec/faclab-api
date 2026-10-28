from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.inventory.stock.domain.entities import Stock
from src.pos.sales.app.commands.confirm_sale import (
    POSConfirmSaleCommand,
    POSConfirmSaleCommandHandler,
)
from src.pos.shift.domain.entities import Shift, ShiftStatus
from src.pos.shift.domain.exceptions import NoOpenShiftError
from src.pos.terminal.app.stock import TerminalStock
from src.sales.domain.entities import Payment, PaymentMethod, Sale, SaleItem, SaleStatus
from tests.unit.pos.terminals import numbering


def _make_sale(**overrides) -> Sale:
    defaults: dict[str, Any] = {
        "id": 1,
        "customer_id": 10,
        "shift_id": 1,
        "status": SaleStatus.DRAFT,
        "subtotal": Decimal("100"),
        "total": Decimal("100"),
    }
    defaults.update(overrides)
    return Sale(**defaults)


def _make_sale_item(**overrides) -> SaleItem:
    defaults: dict[str, Any] = {
        "id": 1,
        "sale_id": 1,
        "product_id": 100,
        "quantity": 2,
        "unit_price": Decimal("50.00"),
        "discount": Decimal("0"),
    }
    defaults.update(overrides)
    return SaleItem(**defaults)


def _make_shift(**overrides) -> Shift:
    defaults: dict[str, Any] = {
        "id": 1,
        "cashier_name": "Test Cashier",
        "status": ShiftStatus.OPEN,
        "opening_balance": Decimal("100"),
    }
    defaults.update(overrides)
    return Shift(**defaults)


def _mock_repo(entity=None, entities=None):
    repo = MagicMock()
    if entity is not None:
        repo.create.return_value = entity
        repo.update.return_value = entity
        repo.get_by_id.return_value = entity
        repo.first.return_value = entity
        repo.first_for_update.return_value = entity
    if entities is not None:
        repo.filter_by.return_value = entities
    return repo


def _make_stock() -> Stock:
    return Stock(id=1, product_id=100, quantity=100)


def _paid_in_full():
    """The payments of a sale of 100, in cash"""
    payment = Payment(
        id=1, sale_id=1, amount=Decimal("100"), payment_method=PaymentMethod.CASH
    )
    return _mock_repo(entities=[payment])


def test_confirm_sale_with_open_shift():
    """Test confirmar venta cuando el turno esta abierto"""
    sale = _make_sale()
    item = _make_sale_item()
    shift = _make_shift(status=ShiftStatus.OPEN)
    stock = _make_stock()

    sale_repo = _mock_repo(entity=sale)
    sale_item_repo = _mock_repo(entities=[item])
    movement_repo = _mock_repo()
    stock_repo = _mock_repo(entity=stock)
    shift_repo = _mock_repo(entity=shift)
    event_publisher = MagicMock()

    handler = POSConfirmSaleCommandHandler(
        sale_repo,
        sale_item_repo,
        TerminalStock(stock_repo, movement_repo),
        shift_repo,
        MagicMock(),
        _paid_in_full(),
        numbering(),
        event_publisher,
    )

    result = handler.handle(POSConfirmSaleCommand(sale_id=1))

    assert result["status"] == "CONFIRMED"
    sale_repo.update.assert_called()


def test_confirm_sale_shift_closed_raises_error():
    """Test error al confirmar venta con turno cerrado"""
    sale = _make_sale(shift_id=1)
    shift = _make_shift(status=ShiftStatus.CLOSED)

    sale_repo = _mock_repo(entity=sale)
    sale_item_repo = _mock_repo()
    movement_repo = _mock_repo()
    stock_repo = _mock_repo()
    shift_repo = _mock_repo(entity=shift)
    event_publisher = MagicMock()

    handler = POSConfirmSaleCommandHandler(
        sale_repo,
        sale_item_repo,
        TerminalStock(stock_repo, movement_repo),
        shift_repo,
        MagicMock(),
        _mock_repo(entities=[]),
        numbering(),
        event_publisher,
    )

    with pytest.raises(NoOpenShiftError):
        handler.handle(POSConfirmSaleCommand(sale_id=1))


def test_confirm_sale_no_shift_linked():
    """Test confirmar venta sin turno vinculado (venta admin) funciona"""
    sale = _make_sale(shift_id=None)
    item = _make_sale_item()
    stock = _make_stock()

    sale_repo = _mock_repo(entity=sale)
    sale_item_repo = _mock_repo(entities=[item])
    movement_repo = _mock_repo()
    stock_repo = _mock_repo(entity=stock)
    shift_repo = _mock_repo()
    event_publisher = MagicMock()

    handler = POSConfirmSaleCommandHandler(
        sale_repo,
        sale_item_repo,
        TerminalStock(stock_repo, movement_repo),
        shift_repo,
        MagicMock(),
        _paid_in_full(),
        numbering(),
        event_publisher,
    )

    result = handler.handle(POSConfirmSaleCommand(sale_id=1))

    assert result["status"] == "CONFIRMED"
