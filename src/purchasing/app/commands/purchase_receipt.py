from dataclasses import dataclass, field, replace
from datetime import datetime

from sqlalchemy.orm import Session
from wireup import injectable

from src.purchasing.app.repositories import (
    PurchaseOrderItemRepository,
    PurchaseOrderRepository,
    PurchaseReceiptItemRepository,
    PurchaseReceiptRepository,
)
from src.purchasing.domain.entities import (
    PurchaseOrderItem,
    PurchaseOrderStatus,
    PurchaseReceipt,
    PurchaseReceiptItem,
)
from src.purchasing.domain.events import PurchaseOrderReceived
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import DomainError, NotFoundError


@dataclass
class ReceiveItemInput:
    purchase_order_item_id: int
    quantity_received: int
    location_id: int | None = None
    lot_number: str | None = None
    serial_numbers: list[str] | None = None


@dataclass
class CreatePurchaseReceiptCommand(Command):
    purchase_order_id: int = 0
    items: list[ReceiveItemInput] = field(default_factory=list)
    notes: str | None = None
    received_at: datetime | None = None

    def __post_init__(self):
        if self.items is None:
            self.items = []


@injectable(lifetime="scoped")
class CreatePurchaseReceiptCommandHandler(
    CommandHandler[CreatePurchaseReceiptCommand, dict]
):
    def __init__(
        self,
        po_repo: PurchaseOrderRepository,
        item_repo: PurchaseOrderItemRepository,
        receipt_repo: PurchaseReceiptRepository,
        receipt_item_repo: PurchaseReceiptItemRepository,
        event_publisher: EventPublisher,
        session: Session,
    ):
        self.po_repo = po_repo
        self.item_repo = item_repo
        self.receipt_repo = receipt_repo
        self.receipt_item_repo = receipt_item_repo
        self.event_publisher = event_publisher
        self.session = session

    def _handle(self, command: CreatePurchaseReceiptCommand) -> dict:
        purchase_order = self.po_repo.get_by_id(command.purchase_order_id)
        if purchase_order is None:
            raise NotFoundError(
                f"Purchase order with id {command.purchase_order_id} not found"
            )

        if purchase_order.status in (
            PurchaseOrderStatus.CANCELLED,
            PurchaseOrderStatus.RECEIVED,
        ):
            raise DomainError(
                f"Cannot receive goods for a purchase order with status '{purchase_order.status.value}'."
            )

        # Validate quantities against pending amounts
        po_items_by_id: dict[int, PurchaseOrderItem] = {
            item.id: item
            for item in self.item_repo.filter_by(
                purchase_order_id=command.purchase_order_id
            )
            if item.id is not None
        }

        for receive_item in command.items:
            po_item = po_items_by_id.get(receive_item.purchase_order_item_id)
            if po_item is None:
                raise NotFoundError(
                    f"Purchase order item with id {receive_item.purchase_order_item_id} not found"
                )
            if receive_item.quantity_received > po_item.quantity_pending:
                raise DomainError(
                    f"Cannot receive {receive_item.quantity_received} units for item {receive_item.purchase_order_item_id}. "
                    f"Only {po_item.quantity_pending} units are pending."
                )

        # Create the receipt
        receipt = PurchaseReceipt(
            purchase_order_id=command.purchase_order_id,
            notes=command.notes,
            received_at=command.received_at or datetime.now(),
        )
        receipt = self.receipt_repo.create(receipt)

        # Create receipt items and update PO item quantities
        receipt_items_data = []
        for receive_item in command.items:
            po_item = po_items_by_id[receive_item.purchase_order_item_id]

            receipt_item = PurchaseReceiptItem(
                purchase_receipt_id=receipt.require_id(),
                purchase_order_item_id=receive_item.purchase_order_item_id,
                product_id=po_item.product_id,
                quantity_received=receive_item.quantity_received,
                location_id=receive_item.location_id,
                lot_number=receive_item.lot_number,
                serial_numbers=receive_item.serial_numbers,
            )
            receipt_item = self.receipt_item_repo.create(receipt_item)
            receipt_items_data.append(
                {
                    "product_id": po_item.product_id,
                    "quantity": receive_item.quantity_received,
                    "location_id": receive_item.location_id,
                    "lot_number": receive_item.lot_number,
                    "serial_numbers": receive_item.serial_numbers or [],
                    "purchase_order_id": command.purchase_order_id,
                }
            )

            updated_item = replace(
                po_item,
                quantity_received=po_item.quantity_received
                + receive_item.quantity_received,
            )
            self.item_repo.update(updated_item)
            po_items_by_id[po_item.require_id()] = updated_item

        # Determine new PO status
        all_received = all(
            item.quantity_pending == 0 for item in po_items_by_id.values()
        )
        if all_received:
            updated_po = purchase_order.mark_received()
        else:
            updated_po = purchase_order.mark_partial()
        updated_po = self.po_repo.update(updated_po)

        self.event_publisher.publish(
            PurchaseOrderReceived(
                aggregate_id=updated_po.require_id(),
                purchase_order_id=updated_po.require_id(),
                order_number=updated_po.order_number,
                is_complete=all_received,
                items=receipt_items_data,
            ),
            session=self.session,
        )

        return receipt.dict()
