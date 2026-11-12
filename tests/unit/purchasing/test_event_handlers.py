from unittest.mock import MagicMock, Mock, patch

from src.purchasing.domain.events import PurchaseOrderReceived


@patch("src.purchasing.infra.event_handlers.create_sync_scope")
def test_handle_purchase_order_received_creates_movements(mock_create_scope):
    """
    Verifies that handle_purchase_order_received creates one IN movement
    per item in the event payload.
    """
    from src.inventory.movement.app.commands.movement import CreateMovementCommand
    from src.inventory.movement.domain.constants import MovementType
    from src.purchasing.infra import event_handlers  # noqa: F401 (registers handler)

    items = [
        {"product_id": 5, "quantity": 10, "location_id": None, "unit_cost": 4},
        {"product_id": 6, "quantity": 3, "location_id": 2, "unit_cost": 7},
    ]

    mock_handler = MagicMock()
    mock_scope = Mock()
    mock_scope.get.return_value = mock_handler
    mock_create_scope.return_value.__enter__.return_value = mock_scope

    event = PurchaseOrderReceived(
        aggregate_id=1,
        purchase_order_id=1,
        order_number="PO-2026-0001",
        is_complete=True,
        items=items,
    )

    from src.purchasing.infra.event_handlers import handle_purchase_order_received

    handle_purchase_order_received(event)

    assert mock_handler.handle.call_count == 2

    first_call = mock_handler.handle.call_args_list[0][0][0]
    assert isinstance(first_call, CreateMovementCommand)
    assert first_call.product_id == 5
    assert first_call.quantity == 10
    assert first_call.type == MovementType.IN.value
    assert first_call.reference_type == "purchase_order"
    assert first_call.reference_id == 1

    # The cost of each line recalculates the location's average (S5.6)
    assert first_call.unit_cost == 4

    second_call = mock_handler.handle.call_args_list[1][0][0]
    assert second_call.product_id == 6
    assert second_call.quantity == 3
    assert second_call.location_id == 2
    assert second_call.unit_cost == 7


@patch("src.purchasing.infra.event_handlers.create_sync_scope")
def test_a_confirmed_supplier_return_takes_the_stock_out(mock_create_scope):
    """S5.7: an OUT movement per line, by product and location, without a cost
    (it leaves at the location's average)"""
    from src.inventory.movement.app.commands.movement import CreateMovementCommand
    from src.inventory.movement.domain.constants import MovementType
    from src.purchasing.domain.events import SupplierReturnConfirmed
    from src.purchasing.infra.event_handlers import handle_supplier_return_confirmed

    mock_handler = MagicMock()
    mock_scope = Mock()
    mock_scope.get.return_value = mock_handler
    mock_create_scope.return_value.__enter__.return_value = mock_scope

    handle_supplier_return_confirmed(
        SupplierReturnConfirmed(
            aggregate_id=3,
            supplier_return_id=3,
            number="DP-2026-0001",
            items=[
                {"product_id": 9, "quantity": 2, "location_id": 1},
                {"product_id": 5, "quantity": 24, "location_id": 4},
            ],
        )
    )

    commands = [call.args[0] for call in mock_handler.handle.call_args_list]
    assert all(isinstance(c, CreateMovementCommand) for c in commands)
    assert [(c.product_id, c.quantity, c.location_id) for c in commands] == [
        (5, -24, 4),
        (9, -2, 1),
    ]
    assert {c.type for c in commands} == {MovementType.OUT.value}
    assert {(c.reference_type, c.reference_id) for c in commands} == {
        ("supplier_return", 3)
    }
    assert {c.unit_cost for c in commands} == {None}
