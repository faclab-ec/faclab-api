from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session
from wireup import injectable

from src.catalog.product.app.quantities import ProductQuantities
from src.inventory.movement.app.repositories import MovementRepository
from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.domain.entities import Movement
from src.inventory.movement.domain.events import MovementCreated
from src.inventory.movement.domain.exceptions import InvalidMovementTypeError
from src.inventory.stock.app.costs import InventoryCosts
from src.inventory.stock.app.repositories import StockRepository
from src.shared.app.audit import AuditAction, AuditTrail
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher


@dataclass
class CreateMovementCommand(Command):
    product_id: int = 0
    quantity: Decimal = Decimal(0)
    type: str = ""  # "in" or "out" string value
    location_id: int | None = None
    source_location_id: int | None = None
    reference_type: str | None = None
    reference_id: int | None = None
    reason: str | None = None
    date: datetime | None = None
    # POST /movements: the audit log keeps it. A document that moves stock
    # audits itself (adjustment, transfer) or is a normal operation (sale)
    manual: bool = False
    # Per base unit, only for an IN (S5.6): the purchase line, the source of a
    # transfer, a counted initial balance. Without it the IN enters at the
    # location's average; an OUT always leaves at that average
    unit_cost: Decimal | None = None


@injectable(lifetime="scoped")
class CreateMovementCommandHandler(CommandHandler[CreateMovementCommand, dict]):
    """
    Maneja la creación de movimientos de inventario.
    Publica el evento MovementCreated que será consumido por el Stock event handler.

    Bloquea antes la fila de stock de la ubicación (la misma que bloquea ese
    handler) para fijar el costo del movimiento: una salida sale al promedio
    vigente y una entrada lleva su costo, que recalcula el promedio (S5.6).
    """

    def __init__(
        self,
        repo: MovementRepository,
        event_publisher: EventPublisher,
        session: Session,
        audit: AuditTrail,
        quantities: ProductQuantities,
        stock_repo: StockRepository,
        costs: InventoryCosts,
    ):
        self.repo = repo
        self.event_publisher = event_publisher
        self.session = session
        self.audit = audit
        self.quantities = quantities
        self.stock_repo = stock_repo
        self.costs = costs

    def _handle(self, command: CreateMovementCommand) -> dict:
        movement_type = MovementType(command.type)
        if command.manual:
            # A document's movements carry quantities it already checked
            self.quantities.ensure([(command.product_id, command.quantity)])
        if movement_type == MovementType.OUT and command.unit_cost is not None:
            raise InvalidMovementTypeError(
                "El costo unitario solo aplica a entradas: una salida sale al "
                "costo promedio de la ubicación"
            )

        stock = self.stock_repo.first_for_update(
            product_id=command.product_id, location_id=command.location_id
        )
        if movement_type == MovementType.OUT:
            unit_cost = self.costs.exit_cost(stock)
        else:
            unit_cost = self.costs.entry_cost(
                command.product_id, stock, command.unit_cost
            )

        movement = Movement(
            product_id=command.product_id,
            quantity=command.quantity,
            type=movement_type,
            location_id=command.location_id,
            source_location_id=command.source_location_id,
            reference_type=command.reference_type,
            reference_id=command.reference_id,
            reason=command.reason,
            date=command.date,
            unit_cost=unit_cost,
        )

        movement = self.repo.create(movement)
        if command.manual:
            self.audit.record(
                AuditAction.MOVEMENT_CREATED,
                movement.require_id(),
                after={
                    "product_id": movement.product_id,
                    "location_id": movement.location_id,
                    "type": movement.type,
                    "quantity": movement.quantity,
                    "unit_cost": movement.unit_cost,
                    "reason": movement.reason,
                },
            )

        self.event_publisher.publish(
            MovementCreated(
                aggregate_id=movement.require_id(),
                product_id=movement.product_id,
                quantity=movement.quantity,
                type=movement.type.value,
                location_id=movement.location_id,
                reason=movement.reason,
                date=movement.date,
                unit_cost=movement.unit_cost,
            ),
            session=self.session,
        )

        return movement.dict()
