from dataclasses import dataclass, replace

from wireup import injectable

from src.inventory.adjustment.app.repositories import (
    AdjustmentItemRepository,
    InventoryAdjustmentRepository,
)
from src.inventory.adjustment.domain.entities import (
    AdjustmentItem,
    AdjustmentReason,
    AdjustmentStatus,
    InventoryAdjustment,
)
from src.inventory.adjustment.domain.events import AdjustmentConfirmed
from src.inventory.movement.app.commands.movement import (
    CreateMovementCommand,
    CreateMovementCommandHandler,
)
from src.inventory.movement.domain.constants import MovementType
from src.inventory.stock.app.repositories import StockRepository
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import DomainError, NotFoundError

# ---------------------------------------------------------------------------
# Adjustment commands
# ---------------------------------------------------------------------------


@dataclass
class CreateAdjustmentCommand(Command):
    warehouse_id: int = 0
    reason: str = ""
    notes: str | None = None
    adjusted_by: str | None = None


@dataclass
class UpdateAdjustmentCommand(Command):
    id: int = 0
    notes: str | None = None
    adjusted_by: str | None = None


@dataclass
class DeleteAdjustmentCommand(Command):
    id: int = 0


@dataclass
class ConfirmAdjustmentCommand(Command):
    id: int = 0


@dataclass
class CancelAdjustmentCommand(Command):
    id: int = 0


# ---------------------------------------------------------------------------
# Adjustment item commands
# ---------------------------------------------------------------------------


@dataclass
class AddAdjustmentItemCommand(Command):
    adjustment_id: int = 0
    product_id: int = 0
    location_id: int = 0
    actual_quantity: int = 0
    lot_id: int | None = None
    notes: str | None = None


@dataclass
class UpdateAdjustmentItemCommand(Command):
    id: int = 0
    actual_quantity: int | None = None
    notes: str | None = None


@dataclass
class RemoveAdjustmentItemCommand(Command):
    id: int = 0


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@injectable(lifetime="scoped")
class CreateAdjustmentCommandHandler(CommandHandler[CreateAdjustmentCommand, dict]):
    def __init__(self, repo: InventoryAdjustmentRepository):
        self.repo = repo

    def _handle(self, command: CreateAdjustmentCommand) -> dict:
        adjustment = InventoryAdjustment(
            warehouse_id=command.warehouse_id,
            reason=AdjustmentReason(command.reason),
            notes=command.notes,
            adjusted_by=command.adjusted_by,
        )
        saved = self.repo.create(adjustment)
        return saved.dict()


@injectable(lifetime="scoped")
class UpdateAdjustmentCommandHandler(CommandHandler[UpdateAdjustmentCommand, dict]):
    def __init__(self, repo: InventoryAdjustmentRepository):
        self.repo = repo

    def _handle(self, command: UpdateAdjustmentCommand) -> dict:
        adjustment = self.repo.get_by_id(command.id)
        if adjustment is None:
            raise NotFoundError(f"Adjustment with id {command.id} not found")
        if adjustment.status != AdjustmentStatus.DRAFT:
            raise DomainError("Solo se pueden actualizar ajustes en DRAFT")

        updated = replace(
            adjustment,
            notes=command.notes if command.notes is not None else adjustment.notes,
            adjusted_by=command.adjusted_by
            if command.adjusted_by is not None
            else adjustment.adjusted_by,
        )
        saved = self.repo.update(updated)
        return saved.dict()


@injectable(lifetime="scoped")
class DeleteAdjustmentCommandHandler(CommandHandler[DeleteAdjustmentCommand, None]):
    def __init__(self, repo: InventoryAdjustmentRepository):
        self.repo = repo

    def _handle(self, command: DeleteAdjustmentCommand) -> None:
        adjustment = self.repo.get_by_id(command.id)
        if adjustment is None:
            raise NotFoundError(f"Adjustment with id {command.id} not found")
        if adjustment.status != AdjustmentStatus.DRAFT:
            raise DomainError("Solo se pueden eliminar ajustes en DRAFT")
        self.repo.delete(command.id)


@injectable(lifetime="scoped")
class ConfirmAdjustmentCommandHandler(CommandHandler[ConfirmAdjustmentCommand, dict]):
    def __init__(
        self,
        repo: InventoryAdjustmentRepository,
        item_repo: AdjustmentItemRepository,
        movement_handler: CreateMovementCommandHandler,
        event_publisher: EventPublisher,
    ):
        self.repo = repo
        self.item_repo = item_repo
        self.movement_handler = movement_handler
        self.event_publisher = event_publisher

    def _handle(self, command: ConfirmAdjustmentCommand) -> dict:
        adjustment = self.repo.get_by_id(command.id)
        if adjustment is None:
            raise NotFoundError(f"Adjustment with id {command.id} not found")

        confirmed = adjustment.confirm()

        items = self.item_repo.filter_by(adjustment_id=adjustment.id)
        adjusted_count = 0

        for item in items:
            diff = item.difference
            if diff == 0:
                continue
            movement_type = MovementType.IN if diff > 0 else MovementType.OUT
            self.movement_handler.handle(
                CreateMovementCommand(
                    product_id=item.product_id,
                    quantity=diff,
                    type=movement_type.value,
                    location_id=item.location_id,
                    reference_type="adjustment",
                    reference_id=adjustment.id,
                    reason=f"Ajuste de inventario: {adjustment.reason.value}",
                )
            )
            adjusted_count += 1

        confirmed = self.repo.update(confirmed)
        self.event_publisher.publish(
            AdjustmentConfirmed(
                aggregate_id=confirmed.require_id(),
                adjustment_id=confirmed.require_id(),
                warehouse_id=confirmed.warehouse_id,
                items_adjusted=adjusted_count,
            )
        )
        return confirmed.dict()


@injectable(lifetime="scoped")
class CancelAdjustmentCommandHandler(CommandHandler[CancelAdjustmentCommand, dict]):
    def __init__(self, repo: InventoryAdjustmentRepository):
        self.repo = repo

    def _handle(self, command: CancelAdjustmentCommand) -> dict:
        adjustment = self.repo.get_by_id(command.id)
        if adjustment is None:
            raise NotFoundError(f"Adjustment with id {command.id} not found")

        cancelled = adjustment.cancel()
        saved = self.repo.update(cancelled)
        return saved.dict()


@injectable(lifetime="scoped")
class AddAdjustmentItemCommandHandler(CommandHandler[AddAdjustmentItemCommand, dict]):
    def __init__(
        self,
        repo: InventoryAdjustmentRepository,
        item_repo: AdjustmentItemRepository,
        stock_repo: StockRepository,
    ):
        self.repo = repo
        self.item_repo = item_repo
        self.stock_repo = stock_repo

    def _handle(self, command: AddAdjustmentItemCommand) -> dict:
        adjustment = self.repo.get_by_id(command.adjustment_id)
        if adjustment is None:
            raise NotFoundError(f"Adjustment with id {command.adjustment_id} not found")
        if adjustment.status != AdjustmentStatus.DRAFT:
            raise DomainError("Solo se pueden agregar ítems a ajustes en DRAFT")

        stock = self.stock_repo.first(
            product_id=command.product_id, location_id=command.location_id
        )
        expected = stock.quantity if stock else 0

        item = AdjustmentItem(
            adjustment_id=command.adjustment_id,
            product_id=command.product_id,
            location_id=command.location_id,
            expected_quantity=expected,
            actual_quantity=command.actual_quantity,
            lot_id=command.lot_id,
            notes=command.notes,
        )
        saved = self.item_repo.create(item)
        return {**saved.dict(), "difference": saved.difference}


@injectable(lifetime="scoped")
class UpdateAdjustmentItemCommandHandler(
    CommandHandler[UpdateAdjustmentItemCommand, dict]
):
    def __init__(
        self, repo: InventoryAdjustmentRepository, item_repo: AdjustmentItemRepository
    ):
        self.repo = repo
        self.item_repo = item_repo

    def _handle(self, command: UpdateAdjustmentItemCommand) -> dict:
        item = self.item_repo.get_by_id(command.id)
        if item is None:
            raise NotFoundError(f"AdjustmentItem with id {command.id} not found")
        adjustment = self.repo.get_by_id(item.adjustment_id)
        if adjustment is None or adjustment.status != AdjustmentStatus.DRAFT:
            raise DomainError("Solo se pueden modificar ítems de ajustes en DRAFT")

        updated = replace(
            item,
            actual_quantity=command.actual_quantity
            if command.actual_quantity is not None
            else item.actual_quantity,
            notes=command.notes if command.notes is not None else item.notes,
        )
        saved = self.item_repo.update(updated)
        return {**saved.dict(), "difference": saved.difference}


@injectable(lifetime="scoped")
class RemoveAdjustmentItemCommandHandler(
    CommandHandler[RemoveAdjustmentItemCommand, None]
):
    def __init__(
        self, repo: InventoryAdjustmentRepository, item_repo: AdjustmentItemRepository
    ):
        self.repo = repo
        self.item_repo = item_repo

    def _handle(self, command: RemoveAdjustmentItemCommand) -> None:
        item = self.item_repo.get_by_id(command.id)
        if item is None:
            raise NotFoundError(f"AdjustmentItem with id {command.id} not found")
        adjustment = self.repo.get_by_id(item.adjustment_id)
        if adjustment is None or adjustment.status != AdjustmentStatus.DRAFT:
            raise DomainError("Solo se pueden eliminar ítems de ajustes en DRAFT")
        self.item_repo.delete(command.id)
