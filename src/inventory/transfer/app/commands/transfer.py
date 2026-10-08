from dataclasses import dataclass, replace

from wireup import injectable

from src.inventory.movement.app.commands.movement import (
    CreateMovementCommand,
    CreateMovementCommandHandler,
)
from src.inventory.movement.domain.constants import MovementType
from src.inventory.stock.app.repositories import StockRepository
from src.inventory.stock.domain.exceptions import InsufficientStockError
from src.inventory.transfer.app.repositories import (
    StockTransferItemRepository,
    StockTransferRepository,
)
from src.inventory.transfer.domain.entities import (
    StockTransfer,
    StockTransferItem,
    TransferStatus,
)
from src.inventory.transfer.domain.events import (
    StockTransferCancelled,
    StockTransferConfirmed,
    StockTransferReceived,
)
from src.inventory.transfer.domain.exceptions import (
    InvalidTransferStatusError,
    SameLocationTransferError,
    TransferHasNoItemsError,
)
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError, ValidationError

# ---------------------------------------------------------------------------
# Transfer commands
# ---------------------------------------------------------------------------


@dataclass
class CreateStockTransferCommand(Command):
    source_location_id: int = 0
    destination_location_id: int = 0
    notes: str | None = None
    requested_by: str | None = None


@dataclass
class UpdateStockTransferCommand(Command):
    id: int = 0
    notes: str | None = None
    requested_by: str | None = None


@dataclass
class DeleteStockTransferCommand(Command):
    id: int = 0


@dataclass
class ConfirmStockTransferCommand(Command):
    id: int = 0


@dataclass
class ReceiveStockTransferCommand(Command):
    id: int = 0


@dataclass
class CancelStockTransferCommand(Command):
    id: int = 0


# ---------------------------------------------------------------------------
# Transfer item commands
# ---------------------------------------------------------------------------


@dataclass
class AddTransferItemCommand(Command):
    transfer_id: int = 0
    product_id: int = 0
    quantity: int = 0
    lot_id: int | None = None
    notes: str | None = None


@dataclass
class UpdateTransferItemCommand(Command):
    id: int = 0
    quantity: int | None = None
    notes: str | None = None


@dataclass
class RemoveTransferItemCommand(Command):
    id: int = 0


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@injectable(lifetime="scoped")
class CreateStockTransferCommandHandler(
    CommandHandler[CreateStockTransferCommand, dict]
):
    def __init__(self, repo: StockTransferRepository):
        self.repo = repo

    def _handle(self, command: CreateStockTransferCommand) -> dict:
        if command.source_location_id == command.destination_location_id:
            raise SameLocationTransferError()
        transfer = StockTransfer(
            source_location_id=command.source_location_id,
            destination_location_id=command.destination_location_id,
            notes=command.notes,
            requested_by=command.requested_by,
        )
        saved = self.repo.create(transfer)
        return saved.dict()


@injectable(lifetime="scoped")
class UpdateStockTransferCommandHandler(
    CommandHandler[UpdateStockTransferCommand, dict]
):
    def __init__(self, repo: StockTransferRepository):
        self.repo = repo

    def _handle(self, command: UpdateStockTransferCommand) -> dict:
        transfer = self.repo.get_by_id(command.id)
        if transfer is None:
            raise NotFoundError(f"StockTransfer with id {command.id} not found")
        if transfer.status != TransferStatus.DRAFT:
            raise InvalidTransferStatusError(transfer.status, "actualizar")

        updated = replace(
            transfer,
            notes=command.notes if command.notes is not None else transfer.notes,
            requested_by=command.requested_by
            if command.requested_by is not None
            else transfer.requested_by,
        )
        saved = self.repo.update(updated)
        return saved.dict()


@injectable(lifetime="scoped")
class DeleteStockTransferCommandHandler(
    CommandHandler[DeleteStockTransferCommand, None]
):
    def __init__(self, repo: StockTransferRepository):
        self.repo = repo

    def _handle(self, command: DeleteStockTransferCommand) -> None:
        transfer = self.repo.get_by_id(command.id)
        if transfer is None:
            raise NotFoundError(f"StockTransfer with id {command.id} not found")
        if transfer.status != TransferStatus.DRAFT:
            raise InvalidTransferStatusError(transfer.status, "eliminar")
        self.repo.delete(command.id)


@injectable(lifetime="scoped")
class ConfirmStockTransferCommandHandler(
    CommandHandler[ConfirmStockTransferCommand, dict]
):
    def __init__(
        self,
        repo: StockTransferRepository,
        item_repo: StockTransferItemRepository,
        stock_repo: StockRepository,
        event_publisher: EventPublisher,
    ):
        self.repo = repo
        self.item_repo = item_repo
        self.stock_repo = stock_repo
        self.event_publisher = event_publisher

    def _handle(self, command: ConfirmStockTransferCommand) -> dict:
        transfer = self.repo.get_by_id(command.id)
        if transfer is None:
            raise NotFoundError(f"StockTransfer with id {command.id} not found")

        items = self.item_repo.filter_by(transfer_id=transfer.id)
        if not items:
            raise TransferHasNoItemsError(transfer.id)

        for item in items:
            stock = self.stock_repo.first(
                product_id=item.product_id,
                location_id=transfer.source_location_id,
            )
            if stock is None or stock.available_quantity < item.quantity:
                raise InsufficientStockError(item.product_id, item.quantity)
            updated_stock = replace(
                stock,
                reserved_quantity=stock.reserved_quantity + item.quantity,
            )
            self.stock_repo.update(updated_stock)

        confirmed = transfer.confirm()
        saved = self.repo.update(confirmed)
        self.event_publisher.publish(
            StockTransferConfirmed(
                aggregate_id=saved.require_id(),
                transfer_id=saved.require_id(),
                source_location_id=saved.source_location_id,
                destination_location_id=saved.destination_location_id,
                items_reserved=len(items),
            )
        )
        return saved.dict()


@injectable(lifetime="scoped")
class ReceiveStockTransferCommandHandler(
    CommandHandler[ReceiveStockTransferCommand, dict]
):
    def __init__(
        self,
        repo: StockTransferRepository,
        item_repo: StockTransferItemRepository,
        stock_repo: StockRepository,
        movement_handler: CreateMovementCommandHandler,
        event_publisher: EventPublisher,
    ):
        self.repo = repo
        self.item_repo = item_repo
        self.stock_repo = stock_repo
        self.movement_handler = movement_handler
        self.event_publisher = event_publisher

    def _handle(self, command: ReceiveStockTransferCommand) -> dict:
        transfer = self.repo.get_by_id(command.id)
        if transfer is None:
            raise NotFoundError(f"StockTransfer with id {command.id} not found")
        if transfer.status != TransferStatus.CONFIRMED:
            raise InvalidTransferStatusError(transfer.status, "recibir")

        items = self.item_repo.filter_by(transfer_id=transfer.id)

        for item in items:
            # Release reservation in source
            source_stock = self.stock_repo.first(
                product_id=item.product_id,
                location_id=transfer.source_location_id,
            )
            if source_stock is not None:
                updated = replace(
                    source_stock,
                    reserved_quantity=source_stock.reserved_quantity - item.quantity,
                )
                self.stock_repo.update(updated)

            # OUT movement from source
            self.movement_handler.handle(
                CreateMovementCommand(
                    product_id=item.product_id,
                    quantity=-abs(item.quantity),
                    type=MovementType.OUT.value,
                    location_id=transfer.source_location_id,
                    source_location_id=None,
                    reference_type="transfer",
                    reference_id=transfer.id,
                    reason=f"Transferencia #{transfer.id} - salida de origen",
                )
            )

            # IN movement to destination
            self.movement_handler.handle(
                CreateMovementCommand(
                    product_id=item.product_id,
                    quantity=item.quantity,
                    type=MovementType.IN.value,
                    location_id=transfer.destination_location_id,
                    source_location_id=transfer.source_location_id,
                    reference_type="transfer",
                    reference_id=transfer.id,
                    reason=f"Transferencia #{transfer.id} - entrada a destino",
                )
            )

        received = transfer.receive()
        saved = self.repo.update(received)
        self.event_publisher.publish(
            StockTransferReceived(
                aggregate_id=saved.require_id(),
                transfer_id=saved.require_id(),
                source_location_id=saved.source_location_id,
                destination_location_id=saved.destination_location_id,
                items_transferred=len(items),
            )
        )
        return saved.dict()


@injectable(lifetime="scoped")
class CancelStockTransferCommandHandler(
    CommandHandler[CancelStockTransferCommand, dict]
):
    def __init__(
        self,
        repo: StockTransferRepository,
        item_repo: StockTransferItemRepository,
        stock_repo: StockRepository,
        event_publisher: EventPublisher,
    ):
        self.repo = repo
        self.item_repo = item_repo
        self.stock_repo = stock_repo
        self.event_publisher = event_publisher

    def _handle(self, command: CancelStockTransferCommand) -> dict:
        transfer = self.repo.get_by_id(command.id)
        if transfer is None:
            raise NotFoundError(f"StockTransfer with id {command.id} not found")

        was_confirmed = transfer.status == TransferStatus.CONFIRMED

        if was_confirmed:
            items = self.item_repo.filter_by(transfer_id=transfer.id)
            for item in items:
                stock = self.stock_repo.first(
                    product_id=item.product_id,
                    location_id=transfer.source_location_id,
                )
                if stock is not None:
                    updated = replace(
                        stock,
                        reserved_quantity=stock.reserved_quantity - item.quantity,
                    )
                    self.stock_repo.update(updated)

        cancelled = transfer.cancel()
        saved = self.repo.update(cancelled)
        self.event_publisher.publish(
            StockTransferCancelled(
                aggregate_id=saved.require_id(),
                transfer_id=saved.require_id(),
                was_confirmed=was_confirmed,
            )
        )
        return saved.dict()


@injectable(lifetime="scoped")
class AddTransferItemCommandHandler(CommandHandler[AddTransferItemCommand, dict]):
    def __init__(
        self,
        repo: StockTransferRepository,
        item_repo: StockTransferItemRepository,
    ):
        self.repo = repo
        self.item_repo = item_repo

    def _handle(self, command: AddTransferItemCommand) -> dict:
        transfer = self.repo.get_by_id(command.transfer_id)
        if transfer is None:
            raise NotFoundError(
                f"StockTransfer with id {command.transfer_id} not found"
            )
        if transfer.status != TransferStatus.DRAFT:
            raise InvalidTransferStatusError(transfer.status, "agregar ítems a")
        if command.quantity <= 0:
            raise ValidationError("La cantidad debe ser mayor a cero")

        item = StockTransferItem(
            transfer_id=command.transfer_id,
            product_id=command.product_id,
            quantity=command.quantity,
            lot_id=command.lot_id,
            notes=command.notes,
        )
        saved = self.item_repo.create(item)
        return saved.dict()


@injectable(lifetime="scoped")
class UpdateTransferItemCommandHandler(CommandHandler[UpdateTransferItemCommand, dict]):
    def __init__(
        self, repo: StockTransferRepository, item_repo: StockTransferItemRepository
    ):
        self.repo = repo
        self.item_repo = item_repo

    def _handle(self, command: UpdateTransferItemCommand) -> dict:
        item = self.item_repo.get_by_id(command.id)
        if item is None:
            raise NotFoundError(f"StockTransferItem with id {command.id} not found")
        transfer = self.repo.get_by_id(item.transfer_id)
        if transfer is None:
            raise NotFoundError(f"StockTransfer with id {item.transfer_id} not found")
        if transfer.status != TransferStatus.DRAFT:
            raise InvalidTransferStatusError(transfer.status, "modificar ítems de")
        if command.quantity is not None and command.quantity <= 0:
            raise ValidationError("La cantidad debe ser mayor a cero")

        updated = replace(
            item,
            quantity=command.quantity
            if command.quantity is not None
            else item.quantity,
            notes=command.notes if command.notes is not None else item.notes,
        )
        saved = self.item_repo.update(updated)
        return saved.dict()


@injectable(lifetime="scoped")
class RemoveTransferItemCommandHandler(CommandHandler[RemoveTransferItemCommand, None]):
    def __init__(
        self, repo: StockTransferRepository, item_repo: StockTransferItemRepository
    ):
        self.repo = repo
        self.item_repo = item_repo

    def _handle(self, command: RemoveTransferItemCommand) -> None:
        item = self.item_repo.get_by_id(command.id)
        if item is None:
            raise NotFoundError(f"StockTransferItem with id {command.id} not found")
        transfer = self.repo.get_by_id(item.transfer_id)
        if transfer is None:
            raise NotFoundError(f"StockTransfer with id {item.transfer_id} not found")
        if transfer.status != TransferStatus.DRAFT:
            raise InvalidTransferStatusError(transfer.status, "eliminar ítems de")
        self.item_repo.delete(command.id)
