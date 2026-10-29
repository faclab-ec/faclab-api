from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session
from wireup import injectable

from src.inventory.movement.app.repositories import MovementRepository
from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.domain.entities import Movement
from src.inventory.movement.domain.events import MovementCreated
from src.shared.app.audit import AuditAction, AuditTrail
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher


@dataclass
class CreateMovementCommand(Command):
    product_id: int = 0
    quantity: int = 0
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


@injectable(lifetime="scoped")
class CreateMovementCommandHandler(CommandHandler[CreateMovementCommand, dict]):
    """
    Maneja la creación de movimientos de inventario.
    Publica el evento MovementCreated que será consumido por el Stock event handler.
    """

    def __init__(
        self,
        repo: MovementRepository,
        event_publisher: EventPublisher,
        session: Session,
        audit: AuditTrail,
    ):
        self.repo = repo
        self.event_publisher = event_publisher
        self.session = session
        self.audit = audit

    def _handle(self, command: CreateMovementCommand) -> dict:
        movement_type = MovementType(command.type)

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
            ),
            session=self.session,
        )

        return movement.dict()
