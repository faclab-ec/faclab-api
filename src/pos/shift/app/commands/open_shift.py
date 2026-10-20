from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.pos.shift.app.repositories import ShiftRepository
from src.pos.shift.domain.entities import Shift
from src.pos.shift.domain.events import ShiftOpened
from src.pos.shift.domain.exceptions import ShiftAlreadyOpenError
from src.pos.terminal.app.resolver import TerminalRequest, TerminalResolver
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher


@dataclass
class OpenShiftCommand(Command):
    """Comando para abrir un turno en una terminal; el cajero es el usuario
    autenticado"""

    terminal: TerminalRequest
    cashier_name: str
    opening_balance: Decimal
    user_id: int | None = None
    notes: str | None = None


@injectable(lifetime="scoped")
class OpenShiftCommandHandler(CommandHandler[OpenShiftCommand, dict]):
    """Handler para abrir un nuevo turno"""

    def __init__(
        self,
        repo: ShiftRepository,
        terminals: TerminalResolver,
        event_publisher: EventPublisher,
    ):
        self.repo = repo
        self.terminals = terminals
        self.event_publisher = event_publisher

    def _handle(self, command: OpenShiftCommand) -> dict:
        terminal = self.terminals.terminal(command.terminal)
        # The unique index also rejects a concurrent opening in the terminal
        if self.repo.first(terminal_id=terminal.id, status="OPEN") is not None:
            raise ShiftAlreadyOpenError()

        shift = Shift(
            cashier_name=command.cashier_name,
            terminal_id=terminal.require_id(),
            branch_id=terminal.branch_id,
            opened_by_user_id=command.user_id,
            opening_balance=command.opening_balance,
            notes=command.notes,
        )

        shift = self.repo.create(shift)

        self.event_publisher.publish(
            ShiftOpened(
                aggregate_id=shift.require_id(),
                shift_id=shift.require_id(),
                terminal_id=shift.terminal_id,
                cashier_name=shift.cashier_name,
                opening_balance=shift.opening_balance,
            )
        )

        return shift.dict()
