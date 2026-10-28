from dataclasses import dataclass
from datetime import datetime

from wireup import injectable

from src.organization.app.numbering import DocumentNumbering
from src.organization.domain.numbering import DocumentType
from src.purchasing.app.repositories import PurchaseOrderRepository
from src.purchasing.domain.entities import PurchaseOrder
from src.purchasing.domain.events import (
    PurchaseOrderCancelled,
    PurchaseOrderCreated,
    PurchaseOrderSent,
)
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError


@dataclass
class CreatePurchaseOrderCommand(Command):
    supplier_id: int = 0
    notes: str | None = None
    expected_date: datetime | None = None


@injectable(lifetime="scoped")
class CreatePurchaseOrderCommandHandler(
    CommandHandler[CreatePurchaseOrderCommand, dict]
):
    def __init__(
        self,
        repo: PurchaseOrderRepository,
        numbering: DocumentNumbering,
        event_publisher: EventPublisher,
    ):
        self.repo = repo
        self.numbering = numbering
        self.event_publisher = event_publisher

    def _handle(self, command: CreatePurchaseOrderCommand) -> dict:
        # The tenant's counter, locked until the order commits: concurrent
        # orders wait for it instead of colliding, and a deleted draft keeps
        # its number
        order_number = self.numbering.next_in_tenant(
            DocumentType.PURCHASE_ORDER, datetime.now().year
        )

        purchase_order = PurchaseOrder(
            supplier_id=command.supplier_id,
            order_number=order_number,
            notes=command.notes,
            expected_date=command.expected_date,
        )
        purchase_order = self.repo.create(purchase_order)

        self.event_publisher.publish(
            PurchaseOrderCreated(
                aggregate_id=purchase_order.require_id(),
                purchase_order_id=purchase_order.require_id(),
                order_number=purchase_order.order_number,
                supplier_id=purchase_order.supplier_id,
            )
        )
        return purchase_order.dict()


@dataclass
class UpdatePurchaseOrderCommand(Command):
    id: int = 0
    supplier_id: int = 0
    notes: str | None = None
    expected_date: datetime | None = None


@injectable(lifetime="scoped")
class UpdatePurchaseOrderCommandHandler(
    CommandHandler[UpdatePurchaseOrderCommand, dict]
):
    def __init__(self, repo: PurchaseOrderRepository):
        self.repo = repo

    def _handle(self, command: UpdatePurchaseOrderCommand) -> dict:
        purchase_order = self.repo.get_by_id(command.id)
        if purchase_order is None:
            raise NotFoundError(f"Purchase order with id {command.id} not found")

        purchase_order.update_details(
            supplier_id=command.supplier_id,
            notes=command.notes,
            expected_date=command.expected_date,
        )
        updated = self.repo.update(purchase_order)
        return updated.dict()


@dataclass
class DeletePurchaseOrderCommand(Command):
    id: int = 0


@injectable(lifetime="scoped")
class DeletePurchaseOrderCommandHandler(
    CommandHandler[DeletePurchaseOrderCommand, None]
):
    def __init__(self, repo: PurchaseOrderRepository):
        self.repo = repo

    def _handle(self, command: DeletePurchaseOrderCommand) -> None:
        purchase_order = self.repo.get_by_id(command.id)
        if purchase_order is None:
            raise NotFoundError(f"Purchase order with id {command.id} not found")
        purchase_order.ensure_draft("delete")
        self.repo.delete(command.id)


@dataclass
class SendPurchaseOrderCommand(Command):
    id: int = 0


@injectable(lifetime="scoped")
class SendPurchaseOrderCommandHandler(CommandHandler[SendPurchaseOrderCommand, dict]):
    def __init__(self, repo: PurchaseOrderRepository, event_publisher: EventPublisher):
        self.repo = repo
        self.event_publisher = event_publisher

    def _handle(self, command: SendPurchaseOrderCommand) -> dict:
        purchase_order = self.repo.get_by_id(command.id)
        if purchase_order is None:
            raise NotFoundError(f"Purchase order with id {command.id} not found")

        purchase_order.send()
        sent = self.repo.update(purchase_order)

        self.event_publisher.publish(
            PurchaseOrderSent(
                aggregate_id=sent.require_id(),
                purchase_order_id=sent.require_id(),
                order_number=sent.order_number,
            )
        )
        return sent.dict()


@dataclass
class CancelPurchaseOrderCommand(Command):
    id: int = 0


@injectable(lifetime="scoped")
class CancelPurchaseOrderCommandHandler(
    CommandHandler[CancelPurchaseOrderCommand, dict]
):
    def __init__(self, repo: PurchaseOrderRepository, event_publisher: EventPublisher):
        self.repo = repo
        self.event_publisher = event_publisher

    def _handle(self, command: CancelPurchaseOrderCommand) -> dict:
        purchase_order = self.repo.get_by_id(command.id)
        if purchase_order is None:
            raise NotFoundError(f"Purchase order with id {command.id} not found")

        purchase_order.cancel()
        cancelled = self.repo.update(purchase_order)

        self.event_publisher.publish(
            PurchaseOrderCancelled(
                aggregate_id=cancelled.require_id(),
                purchase_order_id=cancelled.require_id(),
                order_number=cancelled.order_number,
            )
        )
        return cancelled.dict()
