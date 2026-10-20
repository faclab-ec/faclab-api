from dataclasses import dataclass

from wireup import injectable

from src.pos.shift.app.repositories import ShiftRepository
from src.pos.shift.domain.exceptions import NoOpenShiftError
from src.pos.terminal.app.resolver import TerminalRequest, TerminalResolver
from src.sales.app.repositories import SaleRepository
from src.sales.domain.entities import Sale
from src.sales.domain.events import SaleCreated
from src.sales.domain.exceptions import CustomerRequiredError
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher


@dataclass
class POSCreateSaleCommand(Command):
    """Comando para crear una venta desde POS (vincula el turno abierto de la
    terminal)"""

    terminal: TerminalRequest
    customer_id: int | None = None
    is_final_consumer: bool = False
    notes: str | None = None
    created_by: str | None = None


@injectable(lifetime="scoped")
class POSCreateSaleCommandHandler(CommandHandler[POSCreateSaleCommand, dict]):
    """Handler para crear una venta POS vinculada al turno de la terminal"""

    def __init__(
        self,
        sale_repo: SaleRepository,
        shift_repo: ShiftRepository,
        terminals: TerminalResolver,
        event_publisher: EventPublisher,
    ):
        self.sale_repo = sale_repo
        self.shift_repo = shift_repo
        self.terminals = terminals
        self.event_publisher = event_publisher

    def _handle(self, command: POSCreateSaleCommand) -> dict:
        terminal = self.terminals.terminal(command.terminal)
        shift = self.shift_repo.first(terminal_id=terminal.id, status="OPEN")
        if shift is None:
            raise NoOpenShiftError()

        # Validar consumidor final
        customer_id = command.customer_id
        if command.is_final_consumer:
            customer_id = None
        elif customer_id is None:
            raise CustomerRequiredError()

        sale = Sale(
            customer_id=customer_id,
            is_final_consumer=command.is_final_consumer,
            shift_id=shift.id,
            branch_id=terminal.branch_id,
            emission_point_id=terminal.emission_point_id,
            terminal_id=terminal.id,
            notes=command.notes,
            created_by=command.created_by,
        )

        sale = self.sale_repo.create(sale)

        self.event_publisher.publish(
            SaleCreated(
                aggregate_id=sale.require_id(),
                sale_id=sale.require_id(),
                customer_id=sale.customer_id,
                total=sale.total,
            )
        )

        return sale.dict()
