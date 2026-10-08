from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.purchasing.app.repositories import (
    PurchaseOrderItemRepository,
    PurchaseOrderRepository,
)
from src.purchasing.domain.entities import PurchaseOrderItem
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class AddPurchaseOrderItemCommand(Command):
    purchase_order_id: int = 0
    product_id: int = 0
    quantity_ordered: int = 1
    unit_cost: Decimal = Decimal("0.00")


@injectable(lifetime="scoped")
class AddPurchaseOrderItemCommandHandler(
    CommandHandler[AddPurchaseOrderItemCommand, dict]
):
    def __init__(
        self,
        item_repo: PurchaseOrderItemRepository,
        po_repo: PurchaseOrderRepository,
    ):
        self.item_repo = item_repo
        self.po_repo = po_repo

    def _handle(self, command: AddPurchaseOrderItemCommand) -> dict:
        purchase_order = self.po_repo.get_by_id(command.purchase_order_id)
        if purchase_order is None:
            raise NotFoundError(
                f"Purchase order with id {command.purchase_order_id} not found"
            )
        purchase_order.ensure_draft("add items to")

        item = PurchaseOrderItem(
            purchase_order_id=command.purchase_order_id,
            product_id=command.product_id,
            quantity_ordered=command.quantity_ordered,
            unit_cost=command.unit_cost,
        )
        item = self.item_repo.create(item)

        all_items = self.item_repo.filter_by(
            purchase_order_id=command.purchase_order_id
        )
        purchase_order.recalculate_totals(all_items)
        self.po_repo.update(purchase_order)

        return item.dict()


@dataclass
class UpdatePurchaseOrderItemCommand(Command):
    id: int = 0
    quantity_ordered: int = 1
    unit_cost: Decimal = Decimal("0.00")


@injectable(lifetime="scoped")
class UpdatePurchaseOrderItemCommandHandler(
    CommandHandler[UpdatePurchaseOrderItemCommand, dict]
):
    def __init__(
        self,
        item_repo: PurchaseOrderItemRepository,
        po_repo: PurchaseOrderRepository,
    ):
        self.item_repo = item_repo
        self.po_repo = po_repo

    def _handle(self, command: UpdatePurchaseOrderItemCommand) -> dict:
        item = self.item_repo.get_by_id(command.id)
        if item is None:
            raise NotFoundError(f"Purchase order item with id {command.id} not found")

        purchase_order = self.po_repo.get_by_id(item.purchase_order_id)
        if purchase_order is None:
            raise NotFoundError(
                f"Purchase order with id {item.purchase_order_id} not found"
            )
        purchase_order.ensure_draft("update items of")

        item.update(
            quantity_ordered=command.quantity_ordered, unit_cost=command.unit_cost
        )
        updated = self.item_repo.update(item)

        all_items = self.item_repo.filter_by(purchase_order_id=item.purchase_order_id)
        purchase_order.recalculate_totals(all_items)
        self.po_repo.update(purchase_order)

        return updated.dict()


@dataclass
class RemovePurchaseOrderItemCommand(Command):
    id: int = 0


@injectable(lifetime="scoped")
class RemovePurchaseOrderItemCommandHandler(
    CommandHandler[RemovePurchaseOrderItemCommand, None]
):
    def __init__(
        self,
        item_repo: PurchaseOrderItemRepository,
        po_repo: PurchaseOrderRepository,
    ):
        self.item_repo = item_repo
        self.po_repo = po_repo

    def _handle(self, command: RemovePurchaseOrderItemCommand) -> None:
        item = self.item_repo.get_by_id(command.id)
        if item is None:
            raise NotFoundError(f"Purchase order item with id {command.id} not found")

        purchase_order = self.po_repo.get_by_id(item.purchase_order_id)
        if purchase_order is None:
            raise NotFoundError(
                f"Purchase order with id {item.purchase_order_id} not found"
            )
        purchase_order.ensure_draft("remove items from")

        self.item_repo.delete(command.id)

        all_items = [
            i
            for i in self.item_repo.filter_by(purchase_order_id=item.purchase_order_id)
            if i.id != command.id
        ]
        purchase_order.recalculate_totals(all_items)
        self.po_repo.update(purchase_order)
