"""Weighted average cost (S5.6): every IN recalculates the average of its
location with its cost, every OUT leaves at it without changing it."""

from dataclasses import replace
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest

from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.domain.entities import Movement
from src.inventory.movement.domain.events import MovementCreated
from src.inventory.stock.domain.entities import Stock, weighted_average
from src.inventory.stock.infra.event_handlers import handle_movement_created
from src.purchasing.domain.entities import PurchaseOrderItem
from src.shared.domain.exceptions import InvalidValueError
from src.shared.domain.money import round_cost
from src.shared.infra.events.event_bus import EventBus
from tests.costs import inventory_costs


@pytest.fixture(autouse=True)
def clear_event_bus():
    EventBus.clear()
    yield
    EventBus.clear()


def _stock(quantity: str, average_cost: str = "0") -> Stock:
    return Stock(
        id=1,
        product_id=10,
        quantity=Decimal(quantity),
        average_cost=Decimal(average_cost),
    )


# --- The average ---


def test_two_purchases_at_different_prices_give_their_weighted_average():
    stock = _stock("0")

    stock.update_quantity(Decimal(10), Decimal("5.00"))
    stock.update_quantity(Decimal(30), Decimal("7.00"))

    # (10 × 5.00 + 30 × 7.00) / 40 = 260.00 / 40
    assert stock.quantity == 40
    assert stock.average_cost == Decimal("6.500000")
    assert stock.value == Decimal("260.00")


def test_without_stock_the_average_is_the_cost_of_the_entry():
    # What was there before (a past average) doesn't weigh: nothing is left
    stock = _stock("0", average_cost="9.00")

    stock.update_quantity(Decimal(4), Decimal("3.25"))

    assert stock.average_cost == Decimal("3.25")


def test_an_out_leaves_at_the_average_and_keeps_it():
    stock = _stock("40", average_cost="6.50")

    stock.update_quantity(Decimal(-15), Decimal("99"))

    assert stock.quantity == 25
    assert stock.average_cost == Decimal("6.50")
    assert stock.value == Decimal("162.50")


def test_an_in_without_cost_enters_at_the_average():
    stock = _stock("10", average_cost="6.50")

    stock.update_quantity(Decimal(5))

    assert (stock.quantity, stock.average_cost) == (15, Decimal("6.50"))


def test_an_in_at_the_average_doesnt_change_it():
    stock = _stock("3", average_cost="0.666667")

    stock.update_quantity(Decimal(7), Decimal("0.666667"))

    assert stock.average_cost == Decimal("0.666667")


def test_the_average_keeps_six_decimals_rounded_half_up():
    # (2 × 1.00 + 1 × 0) / 3 = 0.6666…
    assert weighted_average(
        Decimal(2), Decimal("1.00"), Decimal(1), Decimal(0)
    ) == Decimal("0.666667")
    # Half up at the sixth decimal
    assert round_cost(Decimal("0.0000015")) == Decimal("0.000002")


def test_decimal_quantities_weigh_by_their_fraction():
    stock = _stock("2.5", average_cost="4.00")

    stock.update_quantity(Decimal("0.5"), Decimal("10.00"))

    # (2.5 × 4 + 0.5 × 10) / 3 = 15 / 3
    assert stock.average_cost == Decimal("5.000000")


def test_a_movement_doesnt_take_a_negative_cost():
    with pytest.raises(InvalidValueError):
        Movement(
            product_id=1,
            quantity=Decimal(1),
            type=MovementType.IN,
            unit_cost=Decimal("-1"),
        )


def test_a_movement_value_is_its_signed_quantity_times_its_cost():
    out = Movement(
        product_id=1,
        quantity=Decimal(-3),
        type=MovementType.OUT,
        unit_cost=Decimal("6.50"),
    )

    assert out.value == Decimal("-19.50")


def test_a_purchase_line_in_a_box_costs_each_base_unit_its_share():
    box_of_12 = PurchaseOrderItem(
        purchase_order_id=1,
        product_id=1,
        quantity_ordered=Decimal(2),
        unit_cost=Decimal("30.00"),
        unit_factor=Decimal(12),
    )
    box_of_7 = PurchaseOrderItem(
        purchase_order_id=1,
        product_id=1,
        quantity_ordered=Decimal(1),
        unit_cost=Decimal("10.00"),
        unit_factor=Decimal(7),
    )

    assert box_of_12.base_unit_cost == Decimal("2.500000")
    assert box_of_7.base_unit_cost == Decimal("1.428571")


# --- The cost an IN enters at ---


def test_an_entry_takes_its_own_cost_first():
    costs = inventory_costs({10: Decimal("9.00")})

    assert costs.entry_cost(10, _stock("5", "6.50"), Decimal("7.1234567")) == Decimal(
        "7.123457"
    )


def test_an_entry_without_cost_takes_the_average_of_its_location():
    costs = inventory_costs({10: Decimal("9.00")})

    assert costs.entry_cost(10, _stock("0", "6.50")) == Decimal("6.50")


def test_a_location_that_never_had_it_takes_the_purchase_price_or_zero():
    costs = inventory_costs({10: Decimal("9.00")})

    assert costs.entry_cost(10, None) == Decimal("9.00")
    assert costs.entry_cost(11, None) == 0


def test_an_exit_leaves_at_the_average():
    costs = inventory_costs()

    assert costs.exit_cost(_stock("5", "6.50")) == Decimal("6.50")
    assert costs.exit_cost(None) == 0


# --- The stock handler applies it under the row's lock ---


def _handle(stock: Stock | None, event: MovementCreated) -> Mock:
    repo = Mock()
    repo.first_for_update.return_value = stock
    repo.create.side_effect = lambda s: replace(s, id=1)
    repo.update.side_effect = lambda s: s
    scope = Mock()
    scope.get.return_value = repo
    with patch(
        "src.inventory.stock.infra.event_handlers.create_sync_scope"
    ) as create_scope:
        create_scope.return_value.__enter__.return_value = scope
        handle_movement_created(event)
    return repo


def _event(quantity: str, unit_cost: str, type_: MovementType) -> MovementCreated:
    return MovementCreated(
        aggregate_id=1,
        product_id=10,
        quantity=Decimal(quantity),
        type=type_.value,
        location_id=7,
        unit_cost=Decimal(unit_cost),
    )


def test_an_in_recalculates_the_average_of_the_row():
    repo = _handle(_stock("10", "5.00"), _event("30", "7.00", MovementType.IN))

    updated = repo.update.call_args.args[0]
    assert (updated.quantity, updated.average_cost) == (40, Decimal("6.500000"))


def test_a_new_row_starts_at_the_cost_of_its_first_entry():
    repo = _handle(None, _event("12", "2.50", MovementType.IN))

    created = repo.create.call_args.args[0]
    assert (created.quantity, created.average_cost) == (12, Decimal("2.50"))
    assert created.location_id == 7


def test_an_out_keeps_the_average_of_the_row():
    repo = _handle(_stock("40", "6.50"), _event("-15", "6.50", MovementType.OUT))

    updated = repo.update.call_args.args[0]
    assert (updated.quantity, updated.average_cost) == (25, Decimal("6.50"))
