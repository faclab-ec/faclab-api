from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.sales.app.repositories import PaymentRepository, SaleRepository
from src.sales.domain.entities import Payment, PaymentMethod
from src.sales.domain.events import PaymentReceived
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError, ValidationError


@dataclass
class RegisterPaymentCommand(Command):
    """Comando para registrar un pago"""

    sale_id: int
    amount: Decimal
    payment_method: str
    reference: str | None = None
    notes: str | None = None


@injectable(lifetime="scoped")
class RegisterPaymentCommandHandler(CommandHandler[RegisterPaymentCommand, dict]):
    """Handler para registrar un pago y actualizar el estado de pago de la venta"""

    def __init__(
        self,
        sale_repo: SaleRepository,
        payment_repo: PaymentRepository,
        event_publisher: EventPublisher,
    ):
        self.sale_repo = sale_repo
        self.payment_repo = payment_repo
        self.event_publisher = event_publisher

    def _handle(self, command: RegisterPaymentCommand) -> dict:
        """Registra el pago y actualiza el estado de la venta"""
        # Obtener la venta
        sale = self.sale_repo.get_by_id(command.sale_id)
        if not sale:
            raise NotFoundError(f"Sale with id {command.sale_id} not found")

        # Validar el método de pago
        try:
            payment_method = PaymentMethod(command.payment_method)
        except ValueError:
            raise ValidationError(
                message=f"Invalid payment method: {command.payment_method}",
                detail=f"Valid methods: {[m.value for m in PaymentMethod]}",
            ) from None

        # Crear el pago
        payment = Payment(
            sale_id=command.sale_id,
            amount=command.amount,
            payment_method=payment_method,
            reference=command.reference,
            notes=command.notes,
        )

        payment = self.payment_repo.create(payment)

        # Calcular total pagado
        all_payments = self.payment_repo.filter_by(sale_id=command.sale_id)
        total_paid = sum((p.amount for p in all_payments), Decimal("0"))

        # Actualizar estado de pago de la venta
        sale.update_payment_status(total_paid)
        self.sale_repo.update(sale)

        # Publicar evento
        self.event_publisher.publish(
            PaymentReceived(
                aggregate_id=payment.require_id(),
                payment_id=payment.require_id(),
                sale_id=sale.require_id(),
                amount=payment.amount,
                payment_method=payment.payment_method.value,
                reference=payment.reference or "",
            )
        )

        return payment.dict()
