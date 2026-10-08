from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session
from wireup import injectable

from src.pos.cash.app.queries.get_cash_summary import compute_cash_summary
from src.pos.shift.app.repositories import ShiftRepository
from src.pos.shift.domain.events import ShiftClosed
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError


@dataclass
class CloseShiftCommand(Command):
    """Comando para cerrar un turno"""

    shift_id: int
    closing_balance: Decimal
    notes: str | None = None


@injectable(lifetime="scoped")
class CloseShiftCommandHandler(CommandHandler[CloseShiftCommand, dict]):
    """Handler para cerrar un turno"""

    def __init__(
        self,
        repo: ShiftRepository,
        event_publisher: EventPublisher,
        session: Session,
    ):
        self.repo = repo
        self.event_publisher = event_publisher
        self.session = session

    def _handle(self, command: CloseShiftCommand) -> dict:
        shift = self.repo.get_by_id(command.shift_id)
        if shift is None:
            raise NotFoundError(f"Shift with id {command.shift_id} not found")

        summary = compute_cash_summary(self.session, command.shift_id)
        expected_balance = (
            shift.opening_balance
            + summary["cash_sales"]
            - summary["cash_refunds"]
            + summary["cash_in"]
            - summary["cash_out"]
        )

        discrepancy = shift.close(
            closing_balance=command.closing_balance,
            expected_balance=expected_balance,
        )

        if command.notes is not None:
            shift.notes = command.notes

        self.repo.update(shift)

        self.event_publisher.publish(
            ShiftClosed(
                aggregate_id=shift.require_id(),
                shift_id=shift.require_id(),
                cashier_name=shift.cashier_name,
                closing_balance=command.closing_balance,
                expected_balance=expected_balance,
                discrepancy=discrepancy,
            )
        )

        return shift.dict()
