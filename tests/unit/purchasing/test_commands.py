from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.purchasing.app.commands.purchase_order import (
    CancelPurchaseOrderCommand,
    CancelPurchaseOrderCommandHandler,
    CreatePurchaseOrderCommand,
    CreatePurchaseOrderCommandHandler,
    DeletePurchaseOrderCommand,
    DeletePurchaseOrderCommandHandler,
    SendPurchaseOrderCommand,
    SendPurchaseOrderCommandHandler,
    UpdatePurchaseOrderCommand,
    UpdatePurchaseOrderCommandHandler,
)
from src.purchasing.app.commands.purchase_order_item import (
    AddPurchaseOrderItemCommand,
    AddPurchaseOrderItemCommandHandler,
    RemovePurchaseOrderItemCommand,
    RemovePurchaseOrderItemCommandHandler,
    UpdatePurchaseOrderItemCommand,
    UpdatePurchaseOrderItemCommandHandler,
)
from src.purchasing.app.commands.purchase_receipt import (
    CreatePurchaseReceiptCommand,
    CreatePurchaseReceiptCommandHandler,
    ReceiveItemInput,
)
from src.purchasing.domain.entities import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    PurchaseReceipt,
)
from src.purchasing.domain.exceptions import (
    ExceedsPendingQuantityError,
    InvalidPurchaseOrderStatusError,
)
from src.shared.domain.exceptions import NotFoundError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_po(**overrides) -> PurchaseOrder:
    defaults: dict[str, Any] = {
        "id": 1,
        "supplier_id": 10,
        "order_number": "PO-2026-0001",
        "status": PurchaseOrderStatus.DRAFT,
        "subtotal": Decimal("0.00"),
        "tax": Decimal("0.00"),
        "total": Decimal("0.00"),
    }
    defaults.update(overrides)
    return PurchaseOrder(**defaults)


def _make_item(**overrides) -> PurchaseOrderItem:
    defaults: dict[str, Any] = {
        "id": 1,
        "purchase_order_id": 1,
        "product_id": 5,
        "quantity_ordered": 10,
        "unit_cost": Decimal("25.00"),
        "quantity_received": 0,
    }
    defaults.update(overrides)
    return PurchaseOrderItem(**defaults)


def _make_receipt(**overrides) -> PurchaseReceipt:
    defaults: dict[str, Any] = {
        "id": 1,
        "purchase_order_id": 1,
    }
    defaults.update(overrides)
    return PurchaseReceipt(**defaults)


# ---------------------------------------------------------------------------
# CreatePurchaseOrderCommandHandler
# ---------------------------------------------------------------------------


def test_create_purchase_order_generates_order_number():
    po = _make_po()
    repo = MagicMock()
    repo.last_sequence_for_prefix.return_value = 0
    repo.create.return_value = po
    handler = CreatePurchaseOrderCommandHandler(repo, MagicMock())

    result = handler.handle(CreatePurchaseOrderCommand(supplier_id=10))

    repo.last_sequence_for_prefix.assert_called_once()
    repo.create.assert_called_once()
    assert result["order_number"] == "PO-2026-0001"


def test_create_purchase_order_publishes_event():
    from src.purchasing.domain.events import PurchaseOrderCreated
    from src.shared.infra.events.event_bus import EventBus
    from src.shared.infra.events.event_bus_publisher import EventBusPublisher

    EventBus.clear()
    po = _make_po()
    repo = MagicMock()
    repo.last_sequence_for_prefix.return_value = 2
    repo.create.return_value = po

    events_received = []
    EventBus.subscribe(PurchaseOrderCreated, lambda e: events_received.append(e))

    handler = CreatePurchaseOrderCommandHandler(repo, EventBusPublisher())
    handler.handle(CreatePurchaseOrderCommand(supplier_id=10))

    assert len(events_received) == 1
    assert events_received[0].purchase_order_id == 1
    EventBus.clear()


def test_create_purchase_order_order_number_increments():
    po = _make_po(order_number="PO-2026-0005")
    repo = MagicMock()
    repo.last_sequence_for_prefix.return_value = 4
    repo.create.return_value = po
    handler = CreatePurchaseOrderCommandHandler(repo, MagicMock())

    handler.handle(CreatePurchaseOrderCommand(supplier_id=10))

    # last sequence 4 → next is 5
    called_po = repo.create.call_args[0][0]
    import datetime

    year = datetime.datetime.now().year
    assert called_po.order_number == f"PO-{year}-0005"


# ---------------------------------------------------------------------------
# UpdatePurchaseOrderCommandHandler
# ---------------------------------------------------------------------------


def test_update_purchase_order_draft():
    po = _make_po()
    updated = _make_po(supplier_id=20)
    repo = MagicMock()
    repo.get_by_id.return_value = po
    repo.update.return_value = updated
    handler = UpdatePurchaseOrderCommandHandler(repo)

    result = handler.handle(UpdatePurchaseOrderCommand(id=1, supplier_id=20))
    repo.update.assert_called_once()
    assert result["supplier_id"] == 20


def test_update_purchase_order_non_draft_raises():
    po = _make_po(status=PurchaseOrderStatus.SENT)
    repo = MagicMock()
    repo.get_by_id.return_value = po
    handler = UpdatePurchaseOrderCommandHandler(repo)

    with pytest.raises(InvalidPurchaseOrderStatusError, match="Cannot update"):
        handler.handle(UpdatePurchaseOrderCommand(id=1, supplier_id=20))


def test_update_purchase_order_not_found_raises():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    handler = UpdatePurchaseOrderCommandHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(UpdatePurchaseOrderCommand(id=99, supplier_id=20))


# ---------------------------------------------------------------------------
# DeletePurchaseOrderCommandHandler
# ---------------------------------------------------------------------------


def test_delete_purchase_order_draft():
    po = _make_po()
    repo = MagicMock()
    repo.get_by_id.return_value = po
    handler = DeletePurchaseOrderCommandHandler(repo)

    handler.handle(DeletePurchaseOrderCommand(id=1))
    repo.delete.assert_called_once_with(1)


def test_delete_purchase_order_non_draft_raises():
    po = _make_po(status=PurchaseOrderStatus.SENT)
    repo = MagicMock()
    repo.get_by_id.return_value = po
    handler = DeletePurchaseOrderCommandHandler(repo)

    with pytest.raises(InvalidPurchaseOrderStatusError, match="Cannot delete"):
        handler.handle(DeletePurchaseOrderCommand(id=1))


def test_delete_purchase_order_not_found_raises():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    handler = DeletePurchaseOrderCommandHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(DeletePurchaseOrderCommand(id=99))


# ---------------------------------------------------------------------------
# SendPurchaseOrderCommandHandler
# ---------------------------------------------------------------------------


def test_send_purchase_order():
    po = _make_po(status=PurchaseOrderStatus.DRAFT)
    sent_po = _make_po(status=PurchaseOrderStatus.SENT)
    repo = MagicMock()
    repo.get_by_id.return_value = po
    repo.update.return_value = sent_po
    handler = SendPurchaseOrderCommandHandler(repo, MagicMock())

    result = handler.handle(SendPurchaseOrderCommand(id=1))
    repo.update.assert_called_once()
    assert result["status"] == "sent"


def test_send_purchase_order_publishes_event():
    from src.purchasing.domain.events import PurchaseOrderSent
    from src.shared.infra.events.event_bus import EventBus
    from src.shared.infra.events.event_bus_publisher import EventBusPublisher

    EventBus.clear()
    po = _make_po(status=PurchaseOrderStatus.DRAFT)
    sent_po = _make_po(status=PurchaseOrderStatus.SENT)
    repo = MagicMock()
    repo.get_by_id.return_value = po
    repo.update.return_value = sent_po

    events_received = []
    EventBus.subscribe(PurchaseOrderSent, lambda e: events_received.append(e))

    handler = SendPurchaseOrderCommandHandler(repo, EventBusPublisher())
    handler.handle(SendPurchaseOrderCommand(id=1))

    assert len(events_received) == 1
    EventBus.clear()


def test_send_purchase_order_not_found_raises():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    handler = SendPurchaseOrderCommandHandler(repo, MagicMock())

    with pytest.raises(NotFoundError):
        handler.handle(SendPurchaseOrderCommand(id=99))


# ---------------------------------------------------------------------------
# CancelPurchaseOrderCommandHandler
# ---------------------------------------------------------------------------


def test_cancel_purchase_order():
    po = _make_po(status=PurchaseOrderStatus.SENT)
    cancelled_po = _make_po(status=PurchaseOrderStatus.CANCELLED)
    repo = MagicMock()
    repo.get_by_id.return_value = po
    repo.update.return_value = cancelled_po
    handler = CancelPurchaseOrderCommandHandler(repo, MagicMock())

    result = handler.handle(CancelPurchaseOrderCommand(id=1))
    assert result["status"] == "cancelled"


def test_cancel_purchase_order_publishes_event():
    from src.purchasing.domain.events import PurchaseOrderCancelled
    from src.shared.infra.events.event_bus import EventBus
    from src.shared.infra.events.event_bus_publisher import EventBusPublisher

    EventBus.clear()
    po = _make_po(status=PurchaseOrderStatus.DRAFT)
    cancelled_po = _make_po(status=PurchaseOrderStatus.CANCELLED)
    repo = MagicMock()
    repo.get_by_id.return_value = po
    repo.update.return_value = cancelled_po

    events_received = []
    EventBus.subscribe(PurchaseOrderCancelled, lambda e: events_received.append(e))

    handler = CancelPurchaseOrderCommandHandler(repo, EventBusPublisher())
    handler.handle(CancelPurchaseOrderCommand(id=1))

    assert len(events_received) == 1
    EventBus.clear()


# ---------------------------------------------------------------------------
# AddPurchaseOrderItemCommandHandler
# ---------------------------------------------------------------------------


def test_add_item_to_draft_po():
    po = _make_po()
    item = _make_item()
    po_repo = MagicMock()
    item_repo = MagicMock()
    po_repo.get_by_id.return_value = po
    item_repo.create.return_value = item
    item_repo.filter_by.return_value = [item]
    po_repo.update.return_value = po
    handler = AddPurchaseOrderItemCommandHandler(item_repo, po_repo)

    result = handler.handle(
        AddPurchaseOrderItemCommand(
            purchase_order_id=1,
            product_id=5,
            quantity_ordered=10,
            unit_cost=Decimal("25.00"),
        )
    )

    item_repo.create.assert_called_once()
    po_repo.update.assert_called_once()
    assert result["product_id"] == 5


def test_add_item_to_non_draft_po_raises():
    po = _make_po(status=PurchaseOrderStatus.SENT)
    po_repo = MagicMock()
    item_repo = MagicMock()
    po_repo.get_by_id.return_value = po
    handler = AddPurchaseOrderItemCommandHandler(item_repo, po_repo)

    with pytest.raises(InvalidPurchaseOrderStatusError, match="Cannot add items"):
        handler.handle(
            AddPurchaseOrderItemCommand(
                purchase_order_id=1,
                product_id=5,
                quantity_ordered=10,
                unit_cost=Decimal("10.00"),
            )
        )


# ---------------------------------------------------------------------------
# UpdatePurchaseOrderItemCommandHandler
# ---------------------------------------------------------------------------


def test_update_item():
    item = _make_item()
    updated_item = _make_item(quantity_ordered=20, unit_cost=Decimal("30.00"))
    po = _make_po()
    po_repo = MagicMock()
    item_repo = MagicMock()
    item_repo.get_by_id.return_value = item
    po_repo.get_by_id.return_value = po
    item_repo.update.return_value = updated_item
    item_repo.filter_by.return_value = [updated_item]
    po_repo.update.return_value = po
    handler = UpdatePurchaseOrderItemCommandHandler(item_repo, po_repo)

    result = handler.handle(
        UpdatePurchaseOrderItemCommand(
            id=1, quantity_ordered=20, unit_cost=Decimal("30.00")
        )
    )
    item_repo.update.assert_called_once()
    assert result["quantity_ordered"] == 20


# ---------------------------------------------------------------------------
# RemovePurchaseOrderItemCommandHandler
# ---------------------------------------------------------------------------


def test_remove_item():
    item = _make_item()
    po = _make_po()
    po_repo = MagicMock()
    item_repo = MagicMock()
    item_repo.get_by_id.return_value = item
    po_repo.get_by_id.return_value = po
    item_repo.filter_by.return_value = []
    po_repo.update.return_value = po
    handler = RemovePurchaseOrderItemCommandHandler(item_repo, po_repo)

    handler.handle(RemovePurchaseOrderItemCommand(id=1))
    item_repo.delete.assert_called_once_with(1)


# ---------------------------------------------------------------------------
# CreatePurchaseReceiptCommandHandler
# ---------------------------------------------------------------------------


def _make_receipt_handler():
    po_repo = MagicMock()
    item_repo = MagicMock()
    receipt_repo = MagicMock()
    receipt_item_repo = MagicMock()
    event_publisher = MagicMock()
    return (
        CreatePurchaseReceiptCommandHandler(
            po_repo,
            item_repo,
            receipt_repo,
            receipt_item_repo,
            event_publisher,
            MagicMock(),
        ),
        po_repo,
        item_repo,
        receipt_repo,
        receipt_item_repo,
        event_publisher,
    )


def test_receive_complete():
    handler, po_repo, item_repo, receipt_repo, receipt_item_repo, publisher = (
        _make_receipt_handler()
    )
    po = _make_po(status=PurchaseOrderStatus.SENT)
    item = _make_item(id=1, quantity_ordered=10, quantity_received=0)
    receipt = _make_receipt()

    po_repo.get_by_id.return_value = po
    item_repo.filter_by.return_value = [item]
    receipt_repo.create.return_value = receipt
    receipt_item_repo.create.return_value = MagicMock(id=1)
    item_repo.update.return_value = item
    po_repo.update.return_value = _make_po(status=PurchaseOrderStatus.RECEIVED)

    result = handler.handle(
        CreatePurchaseReceiptCommand(
            purchase_order_id=1,
            items=[ReceiveItemInput(purchase_order_item_id=1, quantity_received=10)],
        )
    )

    assert result["purchase_order_id"] == 1
    publisher.publish.assert_called_once()
    published_event = publisher.publish.call_args[0][0]
    assert published_event.is_complete is True


def test_receive_partial():
    handler, po_repo, item_repo, receipt_repo, receipt_item_repo, publisher = (
        _make_receipt_handler()
    )
    po = _make_po(status=PurchaseOrderStatus.SENT)
    item = _make_item(id=1, quantity_ordered=10, quantity_received=0)
    receipt = _make_receipt()

    po_repo.get_by_id.return_value = po
    item_repo.filter_by.return_value = [item]
    receipt_repo.create.return_value = receipt
    receipt_item_repo.create.return_value = MagicMock(id=1)
    item_repo.update.return_value = _make_item(quantity_ordered=10, quantity_received=5)
    po_repo.update.return_value = _make_po(status=PurchaseOrderStatus.PARTIAL)

    handler.handle(
        CreatePurchaseReceiptCommand(
            purchase_order_id=1,
            items=[ReceiveItemInput(purchase_order_item_id=1, quantity_received=5)],
        )
    )

    published_event = publisher.publish.call_args[0][0]
    assert published_event.is_complete is False


def test_receive_excess_quantity_raises():
    handler, po_repo, item_repo, receipt_repo, receipt_item_repo, publisher = (
        _make_receipt_handler()
    )
    po = _make_po(status=PurchaseOrderStatus.SENT)
    item = _make_item(id=1, quantity_ordered=5, quantity_received=0)

    po_repo.get_by_id.return_value = po
    item_repo.filter_by.return_value = [item]

    with pytest.raises(ExceedsPendingQuantityError, match="Only 5 units are pending"):
        handler.handle(
            CreatePurchaseReceiptCommand(
                purchase_order_id=1,
                items=[
                    ReceiveItemInput(purchase_order_item_id=1, quantity_received=10)
                ],
            )
        )


def test_receive_cancelled_po_raises():
    handler, po_repo, item_repo, receipt_repo, receipt_item_repo, publisher = (
        _make_receipt_handler()
    )
    po = _make_po(status=PurchaseOrderStatus.CANCELLED)
    po_repo.get_by_id.return_value = po

    with pytest.raises(InvalidPurchaseOrderStatusError, match="Cannot receive"):
        handler.handle(
            CreatePurchaseReceiptCommand(
                purchase_order_id=1,
                items=[ReceiveItemInput(purchase_order_item_id=1, quantity_received=5)],
            )
        )


def test_receive_already_received_po_raises():
    handler, po_repo, item_repo, receipt_repo, receipt_item_repo, publisher = (
        _make_receipt_handler()
    )
    po = _make_po(status=PurchaseOrderStatus.RECEIVED)
    po_repo.get_by_id.return_value = po

    with pytest.raises(InvalidPurchaseOrderStatusError, match="Cannot receive"):
        handler.handle(
            CreatePurchaseReceiptCommand(
                purchase_order_id=1,
                items=[ReceiveItemInput(purchase_order_item_id=1, quantity_received=5)],
            )
        )


def test_receive_draft_po_raises():
    handler, po_repo, item_repo, receipt_repo, receipt_item_repo, publisher = (
        _make_receipt_handler()
    )
    po_repo.get_by_id.return_value = _make_po(status=PurchaseOrderStatus.DRAFT)

    with pytest.raises(InvalidPurchaseOrderStatusError, match="status 'draft'"):
        handler.handle(
            CreatePurchaseReceiptCommand(
                purchase_order_id=1,
                items=[ReceiveItemInput(purchase_order_item_id=1, quantity_received=5)],
            )
        )
    receipt_repo.create.assert_not_called()


def test_receive_repeated_item_lines_cannot_exceed_pending():
    handler, po_repo, item_repo, receipt_repo, receipt_item_repo, publisher = (
        _make_receipt_handler()
    )
    po_repo.get_by_id.return_value = _make_po(status=PurchaseOrderStatus.SENT)
    item_repo.filter_by.return_value = [
        _make_item(id=1, quantity_ordered=10, quantity_received=0)
    ]

    # The second line only has 4 units left after the first one
    with pytest.raises(
        ExceedsPendingQuantityError, match="Cannot receive 6 units for item 1"
    ):
        handler.handle(
            CreatePurchaseReceiptCommand(
                purchase_order_id=1,
                items=[
                    ReceiveItemInput(
                        purchase_order_item_id=1, quantity_received=6, lot_number="A"
                    ),
                    ReceiveItemInput(
                        purchase_order_item_id=1, quantity_received=6, lot_number="B"
                    ),
                ],
            )
        )
    receipt_repo.create.assert_not_called()


def test_receive_item_split_across_lines_completes_order():
    handler, po_repo, item_repo, receipt_repo, receipt_item_repo, publisher = (
        _make_receipt_handler()
    )
    po = _make_po(status=PurchaseOrderStatus.SENT)
    po_repo.get_by_id.return_value = po
    item_repo.filter_by.return_value = [
        _make_item(id=1, quantity_ordered=10, quantity_received=0)
    ]
    receipt_repo.create.return_value = _make_receipt()
    receipt_item_repo.create.return_value = MagicMock(id=1)
    po_repo.update.side_effect = lambda updated: updated

    handler.handle(
        CreatePurchaseReceiptCommand(
            purchase_order_id=1,
            items=[
                ReceiveItemInput(
                    purchase_order_item_id=1, quantity_received=4, lot_number="A"
                ),
                ReceiveItemInput(
                    purchase_order_item_id=1, quantity_received=6, lot_number="B"
                ),
            ],
        )
    )

    assert item_repo.update.call_args[0][0].quantity_received == 10
    published_event = publisher.publish.call_args[0][0]
    assert published_event.is_complete is True
    assert len(published_event.items) == 2
