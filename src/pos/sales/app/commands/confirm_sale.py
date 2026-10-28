from dataclasses import dataclass

from sqlalchemy.orm import Session
from wireup import injectable

from src.organization.app.numbering import DocumentNumbering
from src.organization.app.repositories import PosTerminalRepository
from src.organization.domain.numbering import DocumentType
from src.pos.shift.app.repositories import ShiftRepository
from src.pos.shift.domain.entities import ShiftStatus
from src.pos.shift.domain.exceptions import NoOpenShiftError
from src.pos.terminal.app.stock import TerminalStock
from src.sales.app.repositories import (
    PaymentRepository,
    SaleItemRepository,
    SaleRepository,
)
from src.sales.domain.events import SaleConfirmed, sale_items_data, sale_payments_data
from src.sales.domain.exceptions import SaleHasNoItemsError
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError


@dataclass
class POSConfirmSaleCommand(Command):
    sale_id: int


@injectable(lifetime="scoped")
class POSConfirmSaleCommandHandler(CommandHandler[POSConfirmSaleCommand, dict]):
    def __init__(
        self,
        sale_repo: SaleRepository,
        sale_item_repo: SaleItemRepository,
        stock: TerminalStock,
        shift_repo: ShiftRepository,
        terminal_repo: PosTerminalRepository,
        payment_repo: PaymentRepository,
        numbering: DocumentNumbering,
        event_publisher: EventPublisher,
        session: Session,
    ):
        self.sale_repo = sale_repo
        self.sale_item_repo = sale_item_repo
        self.stock = stock
        self.shift_repo = shift_repo
        self.terminal_repo = terminal_repo
        self.payment_repo = payment_repo
        self.numbering = numbering
        self.event_publisher = event_publisher
        self.session = session

    def _handle(self, command: POSConfirmSaleCommand) -> dict:
        sale = self.sale_repo.get_by_id(command.sale_id)
        if not sale:
            raise NotFoundError(f"Sale with id {command.sale_id} not found")

        # Validar que el turno sigue abierto
        if sale.shift_id is not None:
            shift = self.shift_repo.first(id=sale.shift_id)
            if shift is None or shift.status != ShiftStatus.OPEN:
                raise NoOpenShiftError()

        items = self.sale_item_repo.filter_by(sale_id=command.sale_id)
        if not items:
            raise SaleHasNoItemsError(command.sale_id)

        sale.ensure_draft("confirm")
        # The payments cover the total, applied again in the order they were
        # taken because the items may have changed after paying; checked
        # before locking anything
        payments = sorted(
            self.payment_repo.filter_by(sale_id=sale.id), key=lambda p: p.require_id()
        )
        sale.settle(payments)
        for payment in payments:
            self.payment_repo.update(payment)

        # The stock of the terminal's location, not of any other. Stock rows
        # are locked before the number's counter, in every POS document
        terminal = (
            self.terminal_repo.get_by_id(sale.terminal_id)
            if sale.terminal_id is not None
            else None
        )
        self.stock.take(
            items,
            location_id=terminal.default_location_id if terminal else None,
            reason=f"Sale #{command.sale_id} confirmed",
            reference_type="sale",
            reference_id=command.sale_id,
        )

        number = (
            self.numbering.next(sale.branch_id, DocumentType.SALE)
            if sale.branch_id is not None
            else None
        )
        sale.confirm(number)
        self.sale_repo.update(sale)

        self.event_publisher.publish(
            SaleConfirmed(
                aggregate_id=sale.require_id(),
                sale_id=sale.require_id(),
                customer_id=sale.customer_id,
                items=sale_items_data(items),
                subtotal=sale.subtotal,
                total_discount=sale.discount,
                total=sale.total,
                payments=sale_payments_data(payments),
                source="pos",
                branch_id=sale.branch_id,
                emission_point_id=sale.emission_point_id,
                number=sale.number,
            ),
            # Its sales.confirmed message goes to the outbox in this transaction
            session=self.session,
        )

        # Invoicing's handler marked its invoice as pending
        return (self.sale_repo.get_by_id(sale.require_id()) or sale).dict()
