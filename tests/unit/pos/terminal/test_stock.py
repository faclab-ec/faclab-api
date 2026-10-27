from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.domain.entities import Movement
from src.inventory.stock.domain.entities import Stock
from src.pos.terminal.app.stock import TerminalStock
from src.sales.domain.exceptions import InsufficientStockError


@dataclass
class Line:
    product_id: int
    quantity: int


def _stock(
    rows: dict[int, int], reserved: dict[int, int] | None = None
) -> tuple[TerminalStock, MagicMock, MagicMock]:
    """Stock rows of location 7 by product, with `reserved` units of some"""
    reserved = reserved or {}
    stock_repo = MagicMock()
    stock_repo.first_for_update.side_effect = lambda product_id, location_id: (
        Stock(
            id=product_id,
            product_id=product_id,
            quantity=rows[product_id],
            reserved_quantity=reserved.get(product_id, 0),
        )
        if location_id == 7 and product_id in rows
        else None
    )
    movement_repo = MagicMock()
    return TerminalStock(stock_repo, movement_repo), stock_repo, movement_repo


def test_take_locks_by_product_and_writes_out_movements_at_the_location():
    stock, stock_repo, movement_repo = _stock({1: 10, 2: 10})

    stock.take([Line(2, 3), Line(1, 4)], 7, "Sale #5", "sale", 5)

    locked = [
        c.kwargs["product_id"] for c in stock_repo.first_for_update.call_args_list
    ]
    assert locked == [1, 2]
    movements = [c.args[0] for c in movement_repo.create.call_args_list]
    assert [(m.product_id, m.quantity, m.type) for m in movements] == [
        (1, -4, MovementType.OUT),
        (2, -3, MovementType.OUT),
    ]
    assert {(m.location_id, m.reference_type, m.reference_id) for m in movements} == {
        (7, "sale", 5)
    }
    assert [c.args[0].quantity for c in stock_repo.update.call_args_list] == [6, 7]


def test_take_fails_without_enough_at_the_location():
    stock, _, movement_repo = _stock({1: 2})

    with pytest.raises(InsufficientStockError):
        stock.take([Line(1, 3)], 7, "Sale #5", "sale", 5)
    # Another location's stock doesn't count
    with pytest.raises(InsufficientStockError):
        stock.take([Line(1, 1)], 8, "Sale #5", "sale", 5)
    movement_repo.create.assert_not_called()


def test_take_leaves_the_reserved_units():
    """10 units, 6 of them reserved for a transfer: only 4 can be sold"""
    stock, _, movement_repo = _stock({1: 10}, reserved={1: 6})

    with pytest.raises(InsufficientStockError) as error:
        stock.take([Line(1, 5)], 7, "Sale #5", "sale", 5)

    assert (error.value.requested, error.value.available) == (5, 4)
    movement_repo.create.assert_not_called()


def test_take_checks_the_total_of_the_lines_of_a_product():
    stock, stock_repo, movement_repo = _stock({1: 5, 2: 10})

    with pytest.raises(InsufficientStockError) as error:
        stock.take([Line(1, 3), Line(2, 1), Line(1, 3)], 7, "Sale #5", "sale", 5)

    assert (error.value.product_id, error.value.requested) == (1, 6)
    assert error.value.available == 5
    movement_repo.create.assert_not_called()

    # When the total fits: one lock and one stock update per product, one
    # movement per line
    stock_repo.reset_mock()
    stock.take([Line(1, 2), Line(1, 3)], 7, "Sale #6", "sale", 6)

    assert stock_repo.first_for_update.call_count == 1
    assert [c.args[0].quantity for c in stock_repo.update.call_args_list] == [0]
    assert [c.args[0].quantity for c in movement_repo.create.call_args_list] == [
        -2,
        -3,
    ]


def test_put_back_creates_the_row_when_the_location_has_none():
    stock, stock_repo, movement_repo = _stock({1: 5})

    stock.put_back([Line(1, 2), Line(3, 4)], 7, "Refund #2", "refund", 2)

    assert stock_repo.update.call_args.args[0].quantity == 7
    created = stock_repo.create.call_args.args[0]
    assert (created.product_id, created.quantity, created.location_id) == (3, 4, 7)
    assert {m.args[0].type for m in movement_repo.create.call_args_list} == {
        MovementType.IN
    }


def test_taken_from_reads_the_documents_out_movements():
    stock, _, movement_repo = _stock({})
    movement_repo.filter_by.return_value = [
        Movement(product_id=1, quantity=2, type=MovementType.IN, location_id=9),
        Movement(product_id=1, quantity=-2, type=MovementType.OUT, location_id=4),
    ]

    assert stock.taken_from("sale", 5) == 4
    movement_repo.filter_by.assert_called_once_with(
        reference_type="sale", reference_id=5
    )
    movement_repo.filter_by.return_value = []
    assert stock.taken_from("sale", 6) is None
