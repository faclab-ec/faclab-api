from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.catalog.product.app.presentations import ProductPresentations
from src.catalog.product.app.quantities import ProductQuantities
from src.catalog.product.app.repositories import ProductRepository
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
    quantity_ordered: Decimal = Decimal(1)
    unit_cost: Decimal = Decimal("0.00")
    # The presentation it is bought in (S5.2); none: the base unit
    presentation_id: int | None = None


@injectable(lifetime="scoped")
class AddPurchaseOrderItemCommandHandler(
    CommandHandler[AddPurchaseOrderItemCommand, dict]
):
    def __init__(
        self,
        item_repo: PurchaseOrderItemRepository,
        po_repo: PurchaseOrderRepository,
        quantities: ProductQuantities,
        products: ProductRepository,
        presentations: ProductPresentations,
    ):
        self.item_repo = item_repo
        self.po_repo = po_repo
        self.quantities = quantities
        self.products = products
        self.presentations = presentations

    def _handle(self, command: AddPurchaseOrderItemCommand) -> dict:
        purchase_order = self.po_repo.get_by_id(command.purchase_order_id)
        if purchase_order is None:
            raise NotFoundError(
                f"Purchase order with id {command.purchase_order_id} not found"
            )
        purchase_order.ensure_draft("add items to")
        # An unknown product is left to its foreign key (422 REFERENCE_NOT_FOUND)
        product = self.products.get_by_id(command.product_id)
        presentation = (
            self.presentations.resolve(product, command.presentation_id)
            if product is not None
            else None
        )
        factor = presentation.factor if presentation else Decimal(1)
        self.quantities.ensure_in_presentations(
            [(command.product_id, factor, command.quantity_ordered)]
        )

        item = PurchaseOrderItem(
            purchase_order_id=command.purchase_order_id,
            product_id=command.product_id,
            quantity_ordered=command.quantity_ordered,
            unit_cost=command.unit_cost,
            presentation_id=(
                presentation.id if presentation else command.presentation_id
            ),
            unit_factor=factor,
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
    quantity_ordered: Decimal = Decimal(1)
    unit_cost: Decimal = Decimal("0.00")


@injectable(lifetime="scoped")
class UpdatePurchaseOrderItemCommandHandler(
    CommandHandler[UpdatePurchaseOrderItemCommand, dict]
):
    def __init__(
        self,
        item_repo: PurchaseOrderItemRepository,
        po_repo: PurchaseOrderRepository,
        quantities: ProductQuantities,
    ):
        self.item_repo = item_repo
        self.po_repo = po_repo
        self.quantities = quantities

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
        self.quantities.ensure_in_presentations(
            [(item.product_id, item.unit_factor, command.quantity_ordered)]
        )

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
