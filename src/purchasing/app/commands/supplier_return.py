"""Devoluciones a proveedor (S5.7): mercadería recibida de una orden de compra
que vuelve al proveedor. Un borrador junta las líneas; al confirmarse sale del
stock y baja lo que se le debe al proveedor."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session
from wireup import injectable

from src.catalog.product.app.quantities import ProductQuantities
from src.organization.app.numbering import DocumentNumbering
from src.organization.domain.numbering import DocumentType
from src.payables.app.accounts import SupplierAccounts
from src.purchasing.app.repositories import (
    PurchaseOrderItemRepository,
    PurchaseOrderRepository,
    SupplierReturnItemRepository,
    SupplierReturnRepository,
)
from src.purchasing.domain.entities import (
    PurchaseOrderItem,
    SupplierReturn,
    SupplierReturnItem,
    SupplierReturnStatus,
)
from src.purchasing.domain.events import SupplierReturnConfirmed
from src.purchasing.domain.exceptions import (
    ExceedsReturnableQuantityError,
    PurchaseOrderNotReturnableError,
    SupplierReturnItemOutsideOrderError,
)
from src.shared.app.audit import AuditAction, AuditTrail
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError

ZERO = Decimal("0")


def describe_return(supplier_return: SupplierReturn) -> dict[str, Any]:
    """La devolución con lo que queda por reembolsar"""
    return {**supplier_return.dict(), "refund_due": supplier_return.refund_due}


def describe_return_item(item: SupplierReturnItem) -> dict[str, Any]:
    """La línea con su subtotal sin IVA y lo que sale del stock"""
    return {
        **item.dict(),
        "subtotal": item.subtotal,
        "base_quantity": item.base_quantity,
    }


def _get_return(repo: SupplierReturnRepository, id: int) -> SupplierReturn:
    supplier_return = repo.get_by_id(id)
    if supplier_return is None:
        raise NotFoundError(f"Supplier return with id {id} not found")
    return supplier_return


def _get_order_item(repo: PurchaseOrderItemRepository, id: int) -> PurchaseOrderItem:
    item = repo.get_by_id(id)
    if item is None:
        raise NotFoundError(f"Purchase order item with id {id} not found")
    return item


def _recalculate(
    supplier_return: SupplierReturn,
    repo: SupplierReturnRepository,
    item_repo: SupplierReturnItemRepository,
) -> SupplierReturn:
    supplier_return.recalculate_totals(
        item_repo.filter_by(supplier_return_id=supplier_return.require_id())
    )
    return repo.update(supplier_return)


def _ensure_returnable(
    order_item: PurchaseOrderItem,
    lines: list[SupplierReturnItem],
    quantity: Decimal,
    except_line: int | None = None,
) -> None:
    """Lo que el borrador ya devuelve de la línea de la orden, más `quantity`,
    cabe en lo devolvible. Confirmar lo comprueba otra vez con la línea
    bloqueada"""
    taken = sum(
        (
            line.quantity
            for line in lines
            if line.purchase_order_item_id == order_item.id and line.id != except_line
        ),
        ZERO,
    )
    returnable = order_item.quantity_returnable - taken
    if quantity > returnable:
        raise ExceedsReturnableQuantityError(
            order_item.require_id(), quantity, max(returnable, ZERO)
        )


@dataclass
class CreateSupplierReturnCommand(Command):
    purchase_order_id: int = 0
    notes: str | None = None


@injectable(lifetime="scoped")
class CreateSupplierReturnCommandHandler(
    CommandHandler[CreateSupplierReturnCommand, dict]
):
    def __init__(
        self,
        repo: SupplierReturnRepository,
        po_repo: PurchaseOrderRepository,
        po_item_repo: PurchaseOrderItemRepository,
        numbering: DocumentNumbering,
    ):
        self.repo = repo
        self.po_repo = po_repo
        self.po_item_repo = po_item_repo
        self.numbering = numbering

    def _handle(self, command: CreateSupplierReturnCommand) -> dict:
        order = self.po_repo.get_by_id(command.purchase_order_id)
        if order is None:
            raise NotFoundError(
                f"Purchase order with id {command.purchase_order_id} not found"
            )
        items = self.po_item_repo.filter_by(purchase_order_id=order.require_id())
        if not any(item.quantity_returnable > 0 for item in items):
            raise PurchaseOrderNotReturnableError(order.order_number)

        # The tenant's counter, like the purchase order: a deleted draft keeps it
        number = self.numbering.next_in_tenant(
            DocumentType.SUPPLIER_RETURN, datetime.now().year
        )
        supplier_return = self.repo.create(
            SupplierReturn(
                supplier_id=order.supplier_id,
                purchase_order_id=order.require_id(),
                number=number,
                notes=command.notes,
            )
        )
        return describe_return(supplier_return)


@dataclass
class UpdateSupplierReturnCommand(Command):
    id: int = 0
    notes: str | None = None


@injectable(lifetime="scoped")
class UpdateSupplierReturnCommandHandler(
    CommandHandler[UpdateSupplierReturnCommand, dict]
):
    def __init__(self, repo: SupplierReturnRepository):
        self.repo = repo

    def _handle(self, command: UpdateSupplierReturnCommand) -> dict:
        supplier_return = _get_return(self.repo, command.id)
        supplier_return.update_notes(command.notes)
        return describe_return(self.repo.update(supplier_return))


@dataclass
class DeleteSupplierReturnCommand(Command):
    id: int = 0


@injectable(lifetime="scoped")
class DeleteSupplierReturnCommandHandler(
    CommandHandler[DeleteSupplierReturnCommand, None]
):
    def __init__(
        self, repo: SupplierReturnRepository, item_repo: SupplierReturnItemRepository
    ):
        self.repo = repo
        self.item_repo = item_repo

    def _handle(self, command: DeleteSupplierReturnCommand) -> None:
        supplier_return = _get_return(self.repo, command.id)
        supplier_return.ensure_draft("delete")
        for item in self.item_repo.filter_by(supplier_return_id=command.id):
            self.item_repo.delete(item.require_id())
        self.repo.delete(command.id)


@dataclass
class AddSupplierReturnItemCommand(Command):
    supplier_return_id: int = 0
    purchase_order_item_id: int = 0
    quantity: Decimal = Decimal(1)
    location_id: int | None = None


@injectable(lifetime="scoped")
class AddSupplierReturnItemCommandHandler(
    CommandHandler[AddSupplierReturnItemCommand, dict]
):
    def __init__(
        self,
        repo: SupplierReturnRepository,
        item_repo: SupplierReturnItemRepository,
        po_item_repo: PurchaseOrderItemRepository,
        quantities: ProductQuantities,
    ):
        self.repo = repo
        self.item_repo = item_repo
        self.po_item_repo = po_item_repo
        self.quantities = quantities

    def _handle(self, command: AddSupplierReturnItemCommand) -> dict:
        supplier_return = _get_return(self.repo, command.supplier_return_id)
        supplier_return.ensure_draft("add items to")
        order_item = _get_order_item(self.po_item_repo, command.purchase_order_item_id)
        if order_item.purchase_order_id != supplier_return.purchase_order_id:
            raise SupplierReturnItemOutsideOrderError(
                order_item.require_id(), supplier_return.purchase_order_id
            )
        self.quantities.ensure_in_presentations(
            [(order_item.product_id, order_item.unit_factor, command.quantity)]
        )
        lines = self.item_repo.filter_by(
            supplier_return_id=supplier_return.require_id()
        )
        _ensure_returnable(order_item, lines, command.quantity)

        item = self.item_repo.create(
            SupplierReturnItem.of(
                supplier_return.require_id(),
                order_item,
                command.quantity,
                command.location_id,
            )
        )
        _recalculate(supplier_return, self.repo, self.item_repo)
        return describe_return_item(item)


@dataclass
class UpdateSupplierReturnItemCommand(Command):
    id: int = 0
    quantity: Decimal = Decimal(1)
    location_id: int | None = None


@injectable(lifetime="scoped")
class UpdateSupplierReturnItemCommandHandler(
    CommandHandler[UpdateSupplierReturnItemCommand, dict]
):
    def __init__(
        self,
        repo: SupplierReturnRepository,
        item_repo: SupplierReturnItemRepository,
        po_item_repo: PurchaseOrderItemRepository,
        quantities: ProductQuantities,
    ):
        self.repo = repo
        self.item_repo = item_repo
        self.po_item_repo = po_item_repo
        self.quantities = quantities

    def _handle(self, command: UpdateSupplierReturnItemCommand) -> dict:
        item = self.item_repo.get_by_id(command.id)
        if item is None:
            raise NotFoundError(f"Supplier return item with id {command.id} not found")
        supplier_return = _get_return(self.repo, item.supplier_return_id)
        supplier_return.ensure_draft("update items of")
        order_item = _get_order_item(self.po_item_repo, item.purchase_order_item_id)
        self.quantities.ensure_in_presentations(
            [(order_item.product_id, order_item.unit_factor, command.quantity)]
        )
        lines = self.item_repo.filter_by(
            supplier_return_id=supplier_return.require_id()
        )
        _ensure_returnable(order_item, lines, command.quantity, except_line=item.id)

        item.update(command.quantity, command.location_id)
        updated = self.item_repo.update(item)
        _recalculate(supplier_return, self.repo, self.item_repo)
        return describe_return_item(updated)


@dataclass
class RemoveSupplierReturnItemCommand(Command):
    id: int = 0


@injectable(lifetime="scoped")
class RemoveSupplierReturnItemCommandHandler(
    CommandHandler[RemoveSupplierReturnItemCommand, None]
):
    def __init__(
        self, repo: SupplierReturnRepository, item_repo: SupplierReturnItemRepository
    ):
        self.repo = repo
        self.item_repo = item_repo

    def _handle(self, command: RemoveSupplierReturnItemCommand) -> None:
        item = self.item_repo.get_by_id(command.id)
        if item is None:
            raise NotFoundError(f"Supplier return item with id {command.id} not found")
        supplier_return = _get_return(self.repo, item.supplier_return_id)
        supplier_return.ensure_draft("remove items from")
        self.item_repo.delete(command.id)
        _recalculate(supplier_return, self.repo, self.item_repo)


@dataclass
class ConfirmSupplierReturnCommand(Command):
    id: int = 0
    supplier_credit_note_number: str | None = None
    confirmed_by: str | None = None


@injectable(lifetime="scoped")
class ConfirmSupplierReturnCommandHandler(
    CommandHandler[ConfirmSupplierReturnCommand, dict]
):
    """Bloquea la devolución, luego las líneas de la orden (en orden de id),
    luego el stock (los movimientos OUT, por producto y ubicación) y al final
    las cuentas por pagar del proveedor. La recepción bloquea en el mismo orden
    (líneas → stock → cuenta nueva) y un pago solo bloquea cuentas."""

    def __init__(
        self,
        repo: SupplierReturnRepository,
        item_repo: SupplierReturnItemRepository,
        po_item_repo: PurchaseOrderItemRepository,
        accounts: SupplierAccounts,
        event_publisher: EventPublisher,
        session: Session,
        audit: AuditTrail,
    ):
        self.repo = repo
        self.item_repo = item_repo
        self.po_item_repo = po_item_repo
        self.accounts = accounts
        self.event_publisher = event_publisher
        self.session = session
        self.audit = audit

    def _handle(self, command: ConfirmSupplierReturnCommand) -> dict:
        supplier_return = self.repo.first_for_update(id=command.id)
        if supplier_return is None:
            raise NotFoundError(f"Supplier return with id {command.id} not found")
        items = self.item_repo.filter_by(
            supplier_return_id=supplier_return.require_id()
        )
        supplier_return.confirm(
            len(items), command.supplier_credit_note_number, command.confirmed_by
        )

        # What each order line gives back, checked with the line locked
        returned: dict[int, Decimal] = defaultdict(Decimal)
        for item in items:
            returned[item.purchase_order_item_id] += item.quantity
        for order_item in self.po_item_repo.lock(returned):
            order_item.return_goods(returned[order_item.require_id()])
            self.po_item_repo.update(order_item)

        # The stock leaves at each location's average cost (S5.6)
        self.event_publisher.publish(
            SupplierReturnConfirmed(
                aggregate_id=supplier_return.require_id(),
                supplier_return_id=supplier_return.require_id(),
                number=supplier_return.number or "",
                purchase_order_id=supplier_return.purchase_order_id,
                supplier_id=supplier_return.supplier_id,
                items=[
                    {
                        "product_id": item.product_id,
                        "quantity": item.base_quantity,
                        "location_id": item.location_id,
                    }
                    for item in items
                ],
            ),
            session=self.session,
        )

        credited = self.accounts.credit_return(
            supplier_id=supplier_return.supplier_id,
            purchase_order_id=supplier_return.purchase_order_id,
            supplier_return_id=supplier_return.require_id(),
            amount=supplier_return.total,
        )
        supplier_return.record_credit(credited)
        supplier_return = self.repo.update(supplier_return)

        self.audit.record(
            AuditAction.SUPPLIER_RETURN_CONFIRMED,
            supplier_return.require_id(),
            before={"status": SupplierReturnStatus.DRAFT},
            after={
                "status": supplier_return.status,
                "number": supplier_return.number,
                "purchase_order_id": supplier_return.purchase_order_id,
                "supplier_id": supplier_return.supplier_id,
                "supplier_credit_note_number": (
                    supplier_return.supplier_credit_note_number
                ),
                "total": supplier_return.total,
                "credited_amount": supplier_return.credited_amount,
                "refund_due": supplier_return.refund_due,
                "items": [
                    {
                        "product_id": item.product_id,
                        "quantity": item.quantity,
                        "location_id": item.location_id,
                    }
                    for item in items
                ],
            },
        )
        return describe_return(supplier_return)
