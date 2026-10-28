from dataclasses import dataclass

from sqlalchemy.orm import Session
from wireup import injectable

from src.sales.app.repositories import (
    PaymentRepository,
    SaleItemRepository,
    SaleRepository,
)
from src.sales.domain.entities import SaleStatus
from src.sales.domain.events import (
    SaleInvoicingRequested,
    sale_items_data,
    sale_payments_data,
)
from src.sales.domain.exceptions import (
    InvalidSaleStatusError,
    SaleWithoutEmissionPointError,
)
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError


@dataclass
class RequestSaleInvoicingCommand(Command):
    """Vuelve a enviar una venta confirmada a faclab-invoicing"""

    sale_id: int


@injectable(lifetime="scoped")
class RequestSaleInvoicingCommandHandler(
    CommandHandler[RequestSaleInvoicingCommand, dict]
):
    """Publica SaleInvoicingRequested con los datos actuales de la venta.

    Sirve cuando el mensaje original no llegó o el SRI rechazó la factura.
    faclab-invoicing lo ignora si la venta ya tiene una factura que no está
    rechazada, así que reenviar de más no duplica facturas.
    """

    def __init__(
        self,
        sale_repo: SaleRepository,
        sale_item_repo: SaleItemRepository,
        payment_repo: PaymentRepository,
        event_publisher: EventPublisher,
        session: Session,
    ):
        self.sale_repo = sale_repo
        self.sale_item_repo = sale_item_repo
        self.payment_repo = payment_repo
        self.event_publisher = event_publisher
        self.session = session

    def _handle(self, command: RequestSaleInvoicingCommand) -> dict:
        sale = self.sale_repo.get_by_id(command.sale_id)
        if not sale:
            raise NotFoundError(f"Sale with id {command.sale_id} not found")
        if sale.status != SaleStatus.CONFIRMED:
            raise InvalidSaleStatusError(sale.status, "request invoicing for")

        sale_id = sale.require_id()
        # The invoice needs the sale's establishment and emission point
        if sale.emission_point_id is None:
            raise SaleWithoutEmissionPointError(sale_id)
        # Its `pagos` add up to the total: a sale confirmed before S3.3 without
        # covering it fails here instead of reaching the SRI
        payments = sorted(
            self.payment_repo.filter_by(sale_id=sale_id), key=lambda p: p.require_id()
        )
        sale.settle(payments)
        for payment in payments:
            self.payment_repo.update(payment)
        self.sale_repo.update(sale)

        self.event_publisher.publish(
            SaleInvoicingRequested(
                aggregate_id=sale_id,
                sale_id=sale_id,
                customer_id=sale.customer_id,
                items=sale_items_data(self.sale_item_repo.filter_by(sale_id=sale_id)),
                subtotal=sale.subtotal,
                total_discount=sale.discount,
                total=sale.total,
                payments=sale_payments_data(payments),
                source="pos" if sale.shift_id is not None else "admin",
                branch_id=sale.branch_id,
                emission_point_id=sale.emission_point_id,
                number=sale.number,
            ),
            # The message goes to the outbox in this transaction
            session=self.session,
        )
        return sale.dict()
