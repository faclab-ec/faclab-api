from dataclasses import dataclass

from wireup import injectable

from src.sales.app.repositories import SaleRepository
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class RejectSaleInvoiceCommand(Command):
    """Registra que el SRI rechazó la factura de una venta"""

    sale_id: int
    invoice_id: str
    # The SRI's messages, when faclab-invoicing sends them (`reason`)
    reason: str | None = None


@injectable(lifetime="scoped")
class RejectSaleInvoiceCommandHandler(CommandHandler[RejectSaleInvoiceCommand, dict]):
    """Pasa la factura de la venta de PENDING a REJECTED.

    Con la factura rechazada la venta se puede reenviar o cancelar. Los
    mensajes de Kafka pueden llegar más de una vez: si la factura no está
    pendiente, o el rechazo es de la factura que ya se rechazó, no hace nada.
    """

    def __init__(self, sale_repo: SaleRepository):
        self.sale_repo = sale_repo

    def _handle(self, command: RejectSaleInvoiceCommand) -> dict:
        sale = self.sale_repo.get_by_id(command.sale_id)
        if not sale:
            raise NotFoundError(f"Sale with id {command.sale_id} not found")

        if sale.reject_invoice(command.invoice_id, command.reason):
            self.sale_repo.update(sale)
        return sale.dict()
