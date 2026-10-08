from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.inventory.movement.app.repositories import MovementRepository
from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.domain.entities import Movement
from src.inventory.stock.app.repositories import StockRepository
from src.pos.refund.app.repositories import (
    RefundItemRepository,
    RefundPaymentRepository,
    RefundRepository,
)
from src.pos.refund.domain.entities import RefundPayment
from src.pos.refund.domain.events import RefundCompleted
from src.sales.domain.entities import PaymentMethod
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError, ValidationError


@dataclass
class ProcessRefundCommand(Command):
    refund_id: int
    payments: list[dict]


@injectable(lifetime="scoped")
class ProcessRefundCommandHandler(CommandHandler[ProcessRefundCommand, dict]):
    def __init__(
        self,
        refund_repo: RefundRepository,
        refund_item_repo: RefundItemRepository,
        refund_payment_repo: RefundPaymentRepository,
        movement_repo: MovementRepository,
        stock_repo: StockRepository,
        event_publisher: EventPublisher,
    ):
        self.refund_repo = refund_repo
        self.refund_item_repo = refund_item_repo
        self.refund_payment_repo = refund_payment_repo
        self.movement_repo = movement_repo
        self.stock_repo = stock_repo
        self.event_publisher = event_publisher

    def _handle(self, command: ProcessRefundCommand) -> dict:
        refund = self.refund_repo.get_by_id(command.refund_id)
        if not refund:
            raise NotFoundError(f"Refund with id {command.refund_id} not found")

        refund.complete()

        items = self.refund_item_repo.filter_by(refund_id=command.refund_id)

        total_payment = sum(Decimal(str(p["amount"])) for p in command.payments)
        if total_payment < refund.total:
            raise ValidationError(
                message="Payment amount is insufficient",
                detail=f"Total: {refund.total}, paid: {total_payment}",
            )

        created_payments = []
        for payment_data in command.payments:
            try:
                payment_method = PaymentMethod(payment_data["payment_method"])
            except ValueError:
                raise ValidationError(
                    message=f"Invalid payment method: {payment_data['payment_method']}",
                    detail=f"Valid methods: {[m.value for m in PaymentMethod]}",
                ) from None

            payment = RefundPayment(
                refund_id=refund.require_id(),
                amount=Decimal(str(payment_data["amount"])),
                payment_method=payment_method,
                reference=payment_data.get("reference"),
            )
            payment = self.refund_payment_repo.create(payment)
            created_payments.append(payment)

        self.refund_repo.update(refund)

        for item in items:
            movement = Movement(
                product_id=item.product_id,
                quantity=abs(item.quantity),
                type=MovementType.IN,
                reason=f"Refund #{refund.id}",
            )
            self.movement_repo.create(movement)

            stock = self.stock_repo.first(product_id=item.product_id)
            if stock:
                stock.update_quantity(abs(item.quantity))
                self.stock_repo.update(stock)

        items_data = [
            {
                "product_id": item.product_id,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
            }
            for item in items
        ]

        self.event_publisher.publish(
            RefundCompleted(
                aggregate_id=refund.require_id(),
                refund_id=refund.require_id(),
                original_sale_id=refund.original_sale_id,
                items=items_data,
                total=refund.total,
            )
        )

        result = refund.dict()
        result["items"] = [{**item.dict(), "subtotal": item.subtotal} for item in items]
        result["payments"] = [p.dict() for p in created_payments]
        return result
