from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.pos.shift.app.repositories import ShiftRepository
from src.pos.shift.domain.entities import Shift
from src.pos.shift.domain.events import ShiftOpened
from src.pos.shift.domain.exceptions import ShiftAlreadyOpenError
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher


@dataclass
class OpenShiftCommand(Command):
    """Comando para abrir un nuevo turno"""

    cashier_name: str
    opening_balance: Decimal
    notes: str | None = None


@injectable(lifetime="scoped")
class OpenShiftCommandHandler(CommandHandler[OpenShiftCommand, dict]):
    """Handler para abrir un nuevo turno"""

    def __init__(self, repo: ShiftRepository, event_publisher: EventPublisher):
        self.repo = repo
        self.event_publisher = event_publisher

    def _handle(self, command: OpenShiftCommand) -> dict:
        existing = self.repo.first(status="OPEN")
        if existing is not None:
            raise ShiftAlreadyOpenError()

        shift = Shift(
            cashier_name=command.cashier_name,
            opening_balance=command.opening_balance,
            notes=command.notes,
        )

        shift = self.repo.create(shift)

        self.event_publisher.publish(
            ShiftOpened(
                aggregate_id=shift.require_id(),
                shift_id=shift.require_id(),
                cashier_name=shift.cashier_name,
                opening_balance=shift.opening_balance,
            )
        )

        return shift.dict()
