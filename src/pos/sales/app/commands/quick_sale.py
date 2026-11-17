from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.pos.sales.app.checkout import SaleCheckout, SaleOrder, SalePlacement
from src.pos.shift.app.repositories import ShiftRepository
from src.pos.shift.domain.exceptions import NoOpenShiftError
from src.pos.terminal.app.resolver import TerminalRequest, TerminalResolver
from src.quotes.app.conversion import QuoteConversion
from src.shared.app.commands import Command, CommandHandler


@dataclass
class QuickSaleCommand(Command):
    """Comando para venta rapida (checkout completo en un request)"""

    terminal: TerminalRequest
    items: list[dict]
    payments: list[dict]
    customer_id: int | None = None
    discount_type: str | None = None
    discount_value: Decimal = Decimal("0")
    notes: str | None = None
    created_by: str | None = None
    # The quote it converts (S5.4)
    quote_id: int | None = None


@injectable(lifetime="scoped")
class QuickSaleCommandHandler(CommandHandler[QuickSaleCommand, dict]):
    """Handler para venta rapida: crea venta, items, confirma, paga en una
    transaccion, en la terminal y su turno abierto (`SaleCheckout`)"""

    def __init__(
        self,
        shift_repo: ShiftRepository,
        terminals: TerminalResolver,
        quotes: QuoteConversion,
        checkout: SaleCheckout,
    ):
        self.shift_repo = shift_repo
        self.terminals = terminals
        self.quotes = quotes
        self.checkout = checkout

    def _handle(self, command: QuickSaleCommand) -> dict:
        # The terminal's open shift, locked FOR SHARE before anything else: its
        # closing waits for this sale, or this sale finds it closed (S5.9)
        terminal = self.terminals.terminal(command.terminal)
        shift = self.shift_repo.first_for_share(terminal_id=terminal.id, status="OPEN")
        if shift is None:
            raise NoOpenShiftError()

        # The quote it converts, locked before the stock and the counter: in
        # force, of this branch and for this customer (S5.4)
        quote = (
            self.quotes.take(command.quote_id, terminal.branch_id, command.customer_id)
            if command.quote_id is not None
            else None
        )

        return self.checkout.complete(
            SalePlacement(
                branch_id=terminal.branch_id,
                emission_point_id=terminal.emission_point_id,
                location_id=terminal.default_location_id,
                terminal_id=terminal.id,
                shift_id=shift.id,
            ),
            SaleOrder(
                items=command.items,
                payments=command.payments,
                customer_id=command.customer_id,
                discount_type=command.discount_type,
                discount_value=command.discount_value,
                notes=command.notes,
                created_by=command.created_by,
            ),
            quote=quote,
        )
