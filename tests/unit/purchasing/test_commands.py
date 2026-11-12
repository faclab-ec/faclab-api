from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest

from src.catalog.product.domain.entities import Product
from src.organization.domain.numbering import DocumentType
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
from src.shared.domain.tax import TaxCode
from tests.presentations import FakeProductPresentations
from tests.quantities import FakeProductQuantities

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


def _numbering(number: str = "PO-2026-0001") -> MagicMock:
    numbering = MagicMock()
    numbering.next_in_tenant.return_value = number
    return numbering


def test_create_purchase_order_takes_the_tenants_next_number():
    po = _make_po()
    repo = MagicMock()
    repo.create.return_value = po
    numbering = _numbering("PO-2026-0005")
    handler = CreatePurchaseOrderCommandHandler(repo, numbering, MagicMock())

    handler.handle(CreatePurchaseOrderCommand(supplier_id=10))

    numbering.next_in_tenant.assert_called_once_with(
        DocumentType.PURCHASE_ORDER, datetime.now().year
    )
    assert repo.create.call_args[0][0].order_number == "PO-2026-0005"


def test_create_purchase_order_publishes_event():
    from src.purchasing.domain.events import PurchaseOrderCreated
    from src.shared.infra.events.event_bus import EventBus
    from src.shared.infra.events.event_bus_publisher import EventBusPublisher

    EventBus.clear()
    po = _make_po()
    repo = MagicMock()
    repo.create.return_value = po

    events_received = []
    EventBus.subscribe(PurchaseOrderCreated, lambda e: events_received.append(e))

    handler = CreatePurchaseOrderCommandHandler(repo, _numbering(), EventBusPublisher())
    handler.handle(CreatePurchaseOrderCommand(supplier_id=10))

    assert len(events_received) == 1
    assert events_received[0].purchase_order_id == 1
    EventBus.clear()


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


def _products() -> Mock:
    """Every product sells in its base unit"""
    products = Mock()
    products.get_by_id.side_effect = lambda id: Product(
        id=id, sku=f"SKU-{id}", name="Producto", unit_of_measure_id=1
    )
    return products


def test_add_item_to_draft_po():
    po = _make_po()
    item = _make_item()
    po_repo = MagicMock()
    item_repo = MagicMock()
    po_repo.get_by_id.return_value = po
    item_repo.create.return_value = item
    item_repo.filter_by.return_value = [item]
    po_repo.update.return_value = po
    handler = AddPurchaseOrderItemCommandHandler(
        item_repo,
        po_repo,
        FakeProductQuantities(),
        _products(),
        FakeProductPresentations(),
    )

    result = handler.handle(
        AddPurchaseOrderItemCommand(
            purchase_order_id=1,
            product_id=5,
            quantity_ordered=Decimal(10),
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
    handler = AddPurchaseOrderItemCommandHandler(
        item_repo,
        po_repo,
        FakeProductQuantities(),
        _products(),
        FakeProductPresentations(),
    )

    with pytest.raises(InvalidPurchaseOrderStatusError, match="Cannot add items"):
        handler.handle(
            AddPurchaseOrderItemCommand(
                purchase_order_id=1,
                product_id=5,
                quantity_ordered=Decimal(10),
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
    handler = UpdatePurchaseOrderItemCommandHandler(
        item_repo, po_repo, FakeProductQuantities()
    )

    result = handler.handle(
        UpdatePurchaseOrderItemCommand(
            id=1, quantity_ordered=Decimal(20), unit_cost=Decimal("30.00")
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
            FakeProductQuantities(),
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
            items=[
                ReceiveItemInput(
                    purchase_order_item_id=1, quantity_received=Decimal(10)
                )
            ],
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
            items=[
                ReceiveItemInput(purchase_order_item_id=1, quantity_received=Decimal(5))
            ],
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
                    ReceiveItemInput(
                        purchase_order_item_id=1, quantity_received=Decimal(10)
                    )
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
                items=[
                    ReceiveItemInput(
                        purchase_order_item_id=1, quantity_received=Decimal(5)
                    )
                ],
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
                items=[
                    ReceiveItemInput(
                        purchase_order_item_id=1, quantity_received=Decimal(5)
                    )
                ],
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
                items=[
                    ReceiveItemInput(
                        purchase_order_item_id=1, quantity_received=Decimal(5)
                    )
                ],
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
                        purchase_order_item_id=1,
                        quantity_received=Decimal(6),
                        lot_number="A",
                    ),
                    ReceiveItemInput(
                        purchase_order_item_id=1,
                        quantity_received=Decimal(6),
                        lot_number="B",
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
                    purchase_order_item_id=1,
                    quantity_received=Decimal(4),
                    lot_number="A",
                ),
                ReceiveItemInput(
                    purchase_order_item_id=1,
                    quantity_received=Decimal(6),
                    lot_number="B",
                ),
            ],
        )
    )

    assert item_repo.update.call_args[0][0].quantity_received == 10
    published_event = publisher.publish.call_args[0][0]
    assert published_event.is_complete is True
    assert len(published_event.items) == 2


def test_two_boxes_of_100_put_200_units_in_stock():
    """S5.2: received in the line's presentation; stock and lots in base units"""
    handler, po_repo, item_repo, receipt_repo, receipt_item_repo, publisher = (
        _make_receipt_handler()
    )
    po_repo.get_by_id.return_value = _make_po(status=PurchaseOrderStatus.SENT)
    boxes = _make_item(
        id=1,
        quantity_ordered=Decimal(2),
        quantity_received=Decimal(0),
        presentation_id=7,
        unit_factor=Decimal(100),
    )
    item_repo.filter_by.return_value = [boxes]
    receipt_repo.create.return_value = _make_receipt()
    receipt_item_repo.create.side_effect = lambda receipt_item: receipt_item
    po_repo.update.return_value = _make_po(status=PurchaseOrderStatus.RECEIVED)

    handler.handle(
        CreatePurchaseReceiptCommand(
            purchase_order_id=1,
            items=[
                ReceiveItemInput(
                    purchase_order_item_id=1,
                    quantity_received=Decimal(2),
                    location_id=3,
                )
            ],
        )
    )

    created = receipt_item_repo.create.call_args[0][0]
    assert (created.quantity_received, created.base_quantity) == (2, 200)
    [item] = publisher.publish.call_args[0][0].items
    assert (
        item["quantity"],
        item["presentation_id"],
        item["presentation_quantity"],
    ) == (
        200,
        7,
        2,
    )
    # A box at 25.00 puts each of its 100 units at 0.25 (S5.6)
    assert item["unit_cost"] == Decimal("0.25")
    assert boxes.quantity_pending == 0


def test_a_receipt_records_its_totals_and_opens_what_is_owed():
    """S5.7: 5 of a line at 2.50 with 15 % VAT, with the supplier's invoice:
    the receipt totals 14.38 and its account payable is that"""
    accounts = MagicMock()
    po_repo, item_repo, receipt_repo = MagicMock(), MagicMock(), MagicMock()
    handler = CreatePurchaseReceiptCommandHandler(
        po_repo,
        item_repo,
        receipt_repo,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        FakeProductQuantities(),
        accounts,
    )
    item = _make_item(
        id=1,
        quantity_ordered=Decimal(10),
        unit_cost=Decimal("2.50"),
        tax_code=TaxCode.VAT_15,
    )
    item.recalculate_tax()
    po = _make_po(status=PurchaseOrderStatus.SENT)
    po_repo.get_by_id.return_value = po
    po_repo.update.side_effect = lambda entity: entity
    item_repo.filter_by.return_value = [item]
    receipt_repo.create.side_effect = lambda receipt: (
        setattr(receipt, "id", 4) or receipt
    )

    result = handler.handle(
        CreatePurchaseReceiptCommand(
            purchase_order_id=1,
            items=[
                ReceiveItemInput(purchase_order_item_id=1, quantity_received=Decimal(5))
            ],
            supplier_invoice_number="001-002-000000123",
            received_at=datetime(2026, 11, 3, 10, 30),
        )
    )

    assert (result["subtotal"], result["tax"], result["total"]) == (
        Decimal("12.50"),
        Decimal("1.88"),
        Decimal("14.38"),
    )
    assert result["supplier_invoice_number"] == "001-002-000000123"
    assert accounts.open_for_receipt.call_args.kwargs == {
        "supplier_id": 10,
        "purchase_order_id": 1,
        "purchase_receipt_id": 4,
        "amount": Decimal("14.38"),
        "issued_on": datetime(2026, 11, 3).date(),
        "supplier_invoice_number": "001-002-000000123",
    }


def test_a_new_line_takes_its_products_vat():
    item_repo = MagicMock()
    item_repo.create.side_effect = lambda entity: entity
    po_repo = MagicMock()
    po_repo.get_by_id.return_value = _make_po()
    products = MagicMock()
    products.get_by_id.return_value = Product(
        id=5, sku="T-1", name="Tornillo", tax_code=TaxCode.VAT_5
    )
    handler = AddPurchaseOrderItemCommandHandler(
        item_repo,
        po_repo,
        FakeProductQuantities(),
        products,
        FakeProductPresentations(),
    )

    result = handler.handle(
        AddPurchaseOrderItemCommand(
            purchase_order_id=1,
            product_id=5,
            quantity_ordered=Decimal(4),
            unit_cost=Decimal("10.00"),
        )
    )

    assert (result["tax_code"], result["tax_amount"], result["subtotal"]) == (
        TaxCode.VAT_5,
        Decimal("2.00"),
        Decimal("40.00"),
    )
