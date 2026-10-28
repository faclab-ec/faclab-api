from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.organization.app.numbering import DocumentNumbering
from src.organization.app.repositories import PosTerminalRepository
from src.organization.domain.numbering import DocumentType
from src.pos.refund.app.repositories import (
    RefundItemRepository,
    RefundPaymentRepository,
    RefundRepository,
)
from src.pos.refund.domain.entities import RefundPayment
from src.pos.refund.domain.events import RefundCompleted
from src.pos.terminal.app.stock import TerminalStock
from src.sales.domain.entities import PaymentMethod
from src.shared.app.audit import AuditAction, AuditTrail
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError, ValidationError
from src.shared.domain.money import round_money


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
        stock: TerminalStock,
        terminal_repo: PosTerminalRepository,
        numbering: DocumentNumbering,
        event_publisher: EventPublisher,
        audit: AuditTrail,
    ):
        self.refund_repo = refund_repo
        self.refund_item_repo = refund_item_repo
        self.refund_payment_repo = refund_payment_repo
        self.stock = stock
        self.terminal_repo = terminal_repo
        self.numbering = numbering
        self.event_publisher = event_publisher
        self.audit = audit

    def _handle(self, command: ProcessRefundCommand) -> dict:
        refund = self.refund_repo.get_by_id(command.refund_id)
        if not refund:
            raise NotFoundError(f"Refund with id {command.refund_id} not found")

        refund.ensure_pending("complete")
        before_status = refund.status

        items = self.refund_item_repo.filter_by(refund_id=command.refund_id)

        total_payment = sum(
            (Decimal(str(p["amount"])) for p in command.payments), Decimal("0")
        )
        if round_money(total_payment) < refund.total:
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

        # The goods go back to the location of the refund's terminal
        terminal = (
            self.terminal_repo.get_by_id(refund.terminal_id)
            if refund.terminal_id is not None
            else None
        )
        self.stock.put_back(
            items,
            location_id=terminal.default_location_id if terminal else None,
            reason=f"Refund #{refund.id}",
            reference_type="refund",
            reference_id=refund.require_id(),
        )

        # Numbered after the stock, like every POS document
        number = (
            self.numbering.next(refund.branch_id, DocumentType.REFUND)
            if refund.branch_id is not None
            else None
        )
        refund.complete(number)
        self.refund_repo.update(refund)
        # Who approved it: the refund only keeps who asked for it
        self.audit.record(
            AuditAction.REFUND_PROCESSED,
            refund.require_id(),
            before={"status": before_status},
            after={
                "status": refund.status,
                "number": refund.number,
                "original_sale_id": refund.original_sale_id,
                "total": refund.total,
                "payments": [
                    {"payment_method": p.payment_method, "amount": p.amount}
                    for p in created_payments
                ],
            },
            branch_id=refund.branch_id,
        )

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
