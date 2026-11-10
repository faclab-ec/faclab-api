from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.catalog.product.app.presentations import ProductPresentations
from src.catalog.product.app.quantities import ProductQuantities
from src.catalog.product.app.repositories import (
    ProductPresentationRepository,
    ProductRepository,
)
from src.pricing.app.commands.price_lists import price_list_of
from src.pricing.app.repositories import PriceListItemRepository, PriceListRepository
from src.pricing.app.views import item_views
from src.pricing.domain.entities import PriceListItem
from src.shared.app.audit import AuditAction, AuditTrail, changed, snapshot
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError

# What the audit log keeps of an item, besides what identifies it
AUDITED_FIELDS = ("min_quantity", "price")


def _audited(item: PriceListItem) -> dict:
    return {
        "item_id": item.id,
        "product_id": item.product_id,
        "presentation_id": item.presentation_id,
    }


def _item(
    items: PriceListItemRepository, price_list_id: int, item_id: int
) -> PriceListItem:
    item = items.get_by_id(item_id)
    if item is None or item.price_list_id != price_list_id:
        raise NotFoundError(
            f"Item with id {item_id} of price list {price_list_id} not found"
        )
    return item


@dataclass
class CreatePriceListItemCommand(Command):
    price_list_id: int
    product_id: int
    price: Decimal
    # None: the product's base unit
    presentation_id: int | None = None
    min_quantity: Decimal = Decimal(0)


@injectable(lifetime="scoped")
class CreatePriceListItemCommandHandler(
    CommandHandler[CreatePriceListItemCommand, dict]
):
    """El precio de una presentación en una lista, desde una cantidad"""

    def __init__(
        self,
        lists: PriceListRepository,
        items: PriceListItemRepository,
        products: ProductRepository,
        presentations: ProductPresentations,
        presentation_repo: ProductPresentationRepository,
        quantities: ProductQuantities,
        audit: AuditTrail,
    ):
        self.lists = lists
        self.items = items
        self.products = products
        self.presentations = presentations
        self.presentation_repo = presentation_repo
        self.quantities = quantities
        self.audit = audit

    def _handle(self, command: CreatePriceListItemCommand) -> dict:
        price_list = price_list_of(self.lists, command.price_list_id)
        product = self.products.get_by_id(command.product_id)
        if product is None:
            raise NotFoundError(f"Product with id {command.product_id} not found")
        presentation = self.presentations.resolve(product, command.presentation_id)
        price_list.ensure_accepts(command.min_quantity)
        # "From 10 boxes" is a quantity in that presentation
        self.quantities.ensure_for_presentation(
            product, presentation.factor, command.min_quantity
        )
        item = self.items.create(
            PriceListItem(
                price_list_id=price_list.require_id(),
                product_id=product.require_id(),
                presentation_id=presentation.require_id(),
                price=command.price,
                min_quantity=command.min_quantity,
            )
        )
        self.audit.record(
            AuditAction.PRICE_LIST_ITEM_CREATED,
            price_list.require_id(),
            after=_audited(item) | snapshot(item, *AUDITED_FIELDS),
        )
        [view] = item_views([item], self.products, self.presentation_repo)
        return view


@dataclass
class UpdatePriceListItemCommand(Command):
    price_list_id: int
    item_id: int
    price: Decimal
    min_quantity: Decimal = Decimal(0)


@injectable(lifetime="scoped")
class UpdatePriceListItemCommandHandler(
    CommandHandler[UpdatePriceListItemCommand, dict]
):
    """Cambia el precio o la cantidad mínima de un ítem; el producto y la
    presentación no cambian (se borra y se crea otro)"""

    def __init__(
        self,
        lists: PriceListRepository,
        items: PriceListItemRepository,
        products: ProductRepository,
        presentation_repo: ProductPresentationRepository,
        quantities: ProductQuantities,
        audit: AuditTrail,
    ):
        self.lists = lists
        self.items = items
        self.products = products
        self.presentation_repo = presentation_repo
        self.quantities = quantities
        self.audit = audit

    def _handle(self, command: UpdatePriceListItemCommand) -> dict:
        price_list = price_list_of(self.lists, command.price_list_id)
        item = _item(self.items, command.price_list_id, command.item_id)
        price_list.ensure_accepts(command.min_quantity)
        product = self.products.get_by_id(item.product_id)
        presentation = self.presentation_repo.get_by_id(item.presentation_id)
        if product is not None and presentation is not None:
            self.quantities.ensure_for_presentation(
                product, presentation.factor, command.min_quantity
            )
        previous = snapshot(item, *AUDITED_FIELDS)
        item.change(price=command.price, min_quantity=command.min_quantity)
        item = self.items.update(item)
        before, after = changed(previous, snapshot(item, *AUDITED_FIELDS))
        if after:
            self.audit.record(
                AuditAction.PRICE_LIST_ITEM_UPDATED,
                command.price_list_id,
                before=_audited(item) | before,
                after=_audited(item) | after,
            )
        [view] = item_views([item], self.products, self.presentation_repo)
        return view


@dataclass
class DeletePriceListItemCommand(Command):
    price_list_id: int
    item_id: int


@injectable(lifetime="scoped")
class DeletePriceListItemCommandHandler(
    CommandHandler[DeletePriceListItemCommand, None]
):
    def __init__(self, items: PriceListItemRepository, audit: AuditTrail):
        self.items = items
        self.audit = audit

    def _handle(self, command: DeletePriceListItemCommand) -> None:
        item = _item(self.items, command.price_list_id, command.item_id)
        self.items.delete(item.require_id())
        self.audit.record(
            AuditAction.PRICE_LIST_ITEM_DELETED,
            command.price_list_id,
            before=_audited(item) | snapshot(item, *AUDITED_FIELDS),
        )
