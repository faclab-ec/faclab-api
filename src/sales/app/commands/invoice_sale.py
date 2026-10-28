from dataclasses import dataclass

from wireup import injectable

from src.sales.app.repositories import SaleRepository
from src.sales.domain.entities import SaleStatus
from src.sales.domain.events import SaleInvoiced
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError


@dataclass
class InvoiceSaleCommand(Command):
    """Marca una venta como facturada cuando el SRI autoriza su factura"""

    sale_id: int
    invoice_id: str


@injectable(lifetime="scoped")
class InvoiceSaleCommandHandler(CommandHandler[InvoiceSaleCommand, dict]):
    """Pasa la venta de CONFIRMED a INVOICED.

    Los mensajes de Kafka pueden llegar más de una vez: si la venta ya está
    facturada no hace nada.
    """

    def __init__(self, sale_repo: SaleRepository, event_publisher: EventPublisher):
        self.sale_repo = sale_repo
        self.event_publisher = event_publisher

    def _handle(self, command: InvoiceSaleCommand) -> dict:
        sale = self.sale_repo.get_by_id(command.sale_id)
        if not sale:
            raise NotFoundError(f"Sale with id {command.sale_id} not found")

        if sale.status == SaleStatus.INVOICED:
            return sale.dict()

        sale.invoice(command.invoice_id)
        self.sale_repo.update(sale)

        self.event_publisher.publish(
            SaleInvoiced(
                aggregate_id=sale.require_id(),
                sale_id=sale.require_id(),
                customer_id=sale.customer_id,
                invoice_id=command.invoice_id,
                total=sale.total,
            )
        )

        return sale.dict()
