from dataclasses import dataclass

from wireup import injectable

from src.organization.app.repositories import PosTerminalRepository
from src.pos.terminal.app.stock import TerminalStock
from src.sales.app.repositories import SaleItemRepository, SaleRepository
from src.sales.domain.entities import Sale, SaleStatus
from src.sales.domain.events import SaleCancelled
from src.shared.app.audit import AuditAction, AuditTrail
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError


@dataclass
class POSCancelSaleCommand(Command):
    sale_id: int
    reason: str | None = None


@injectable(lifetime="scoped")
class POSCancelSaleCommandHandler(CommandHandler[POSCancelSaleCommand, dict]):
    def __init__(
        self,
        sale_repo: SaleRepository,
        sale_item_repo: SaleItemRepository,
        stock: TerminalStock,
        terminal_repo: PosTerminalRepository,
        event_publisher: EventPublisher,
        audit: AuditTrail,
    ):
        self.sale_repo = sale_repo
        self.sale_item_repo = sale_item_repo
        self.stock = stock
        self.terminal_repo = terminal_repo
        self.event_publisher = event_publisher
        self.audit = audit

    def _handle(self, command: POSCancelSaleCommand) -> dict:
        sale = self.sale_repo.get_by_id(command.sale_id)
        if not sale:
            raise NotFoundError(f"Sale with id {command.sale_id} not found")

        before = {"status": sale.status, "total": sale.total}
        was_confirmed = sale.status == SaleStatus.CONFIRMED
        items_data = []

        if was_confirmed:
            items = self.sale_item_repo.filter_by(sale_id=command.sale_id)
            sale.cancel()
            self.sale_repo.update(sale)

            self.stock.put_back(
                items,
                location_id=self._taken_from(sale),
                reason=f"Sale #{command.sale_id} cancelled - reversal",
                reference_type="sale",
                reference_id=command.sale_id,
            )

            items_data = [
                {"product_id": item.product_id, "quantity": item.quantity}
                for item in items
            ]
        else:
            sale.cancel()
            self.sale_repo.update(sale)

        self.audit.record(
            AuditAction.SALE_CANCELLED,
            sale.require_id(),
            before=before,
            after={"status": sale.status, "reason": command.reason},
            branch_id=sale.branch_id,
        )
        self.event_publisher.publish(
            SaleCancelled(
                aggregate_id=sale.require_id(),
                sale_id=sale.require_id(),
                customer_id=sale.customer_id,
                items=items_data,
                reason=command.reason or "",
                was_confirmed=was_confirmed,
                source="pos",
            )
        )

        return sale.dict()

    def _taken_from(self, sale: Sale) -> int | None:
        """Where the sale took its stock from: its OUT movements say it, even if
        the terminal sells from another location now"""
        location_id = self.stock.taken_from("sale", sale.require_id())
        if location_id is None and sale.terminal_id is not None:
            terminal = self.terminal_repo.get_by_id(sale.terminal_id)
            if terminal is not None:
                location_id = terminal.default_location_id
        return location_id
