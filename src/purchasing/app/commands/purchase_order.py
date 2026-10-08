from dataclasses import dataclass, replace
from datetime import datetime

from wireup import injectable

from src.purchasing.app.repositories import PurchaseOrderRepository
from src.purchasing.domain.entities import PurchaseOrder, PurchaseOrderStatus
from src.purchasing.domain.events import (
    PurchaseOrderCancelled,
    PurchaseOrderCreated,
    PurchaseOrderSent,
)
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import DomainError, NotFoundError


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
        event_publisher: EventPublisher,
    ):
        self.repo = repo
        self.event_publisher = event_publisher

    def _handle(self, command: CreatePurchaseOrderCommand) -> dict:
        year = datetime.now().year
        count = self.repo.count_by_year(year)
        order_number = f"PO-{year}-{count + 1:04d}"

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
        if purchase_order.status != PurchaseOrderStatus.DRAFT:
            raise DomainError(
                f"Cannot update a purchase order with status '{purchase_order.status.value}'. Only DRAFT orders can be updated."
            )

        updated = replace(
            purchase_order,
            supplier_id=command.supplier_id,
            notes=command.notes,
            expected_date=command.expected_date,
        )
        updated = self.repo.update(updated)
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
        if purchase_order.status != PurchaseOrderStatus.DRAFT:
            raise DomainError(
                f"Cannot delete a purchase order with status '{purchase_order.status.value}'. Only DRAFT orders can be deleted."
            )
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

        sent = purchase_order.send()
        sent = self.repo.update(sent)

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

        cancelled = purchase_order.cancel()
        cancelled = self.repo.update(cancelled)

        self.event_publisher.publish(
            PurchaseOrderCancelled(
                aggregate_id=cancelled.require_id(),
                purchase_order_id=cancelled.require_id(),
                order_number=cancelled.order_number,
            )
        )
        return cancelled.dict()
