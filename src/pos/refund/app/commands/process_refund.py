from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session
from wireup import injectable

from src.invoicing.app.repositories import CreditNoteRepository
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
from src.pos.refund.domain.exceptions import (
    FinalConsumerRefundNotAllowedError,
    SaleNotConfirmedError,
)
from src.pos.terminal.app.stock import TerminalStock
from src.receivables.app.credit import CustomerCredit
from src.receivables.domain.exceptions import CreditPaymentNotAllowedError
from src.sales.app.repositories import SaleRepository
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
    # FINAL_CONSUMER_REFUNDS_ALLOWED: refund it without a credit note
    final_consumer_allowed: bool = False


@injectable(lifetime="scoped")
class ProcessRefundCommandHandler(CommandHandler[ProcessRefundCommand, dict]):
    def __init__(
        self,
        refund_repo: RefundRepository,
        refund_item_repo: RefundItemRepository,
        refund_payment_repo: RefundPaymentRepository,
        sale_repo: SaleRepository,
        credit_notes: CreditNoteRepository,
        stock: TerminalStock,
        terminal_repo: PosTerminalRepository,
        numbering: DocumentNumbering,
        event_publisher: EventPublisher,
        audit: AuditTrail,
        session: Session,
        credit: CustomerCredit,
    ):
        self.credit = credit
        self.refund_repo = refund_repo
        self.refund_item_repo = refund_item_repo
        self.refund_payment_repo = refund_payment_repo
        self.sale_repo = sale_repo
        self.credit_notes = credit_notes
        self.stock = stock
        self.terminal_repo = terminal_repo
        self.numbering = numbering
        self.event_publisher = event_publisher
        self.audit = audit
        self.session = session

    def _handle(self, command: ProcessRefundCommand) -> dict:
        refund = self.refund_repo.get_by_id(command.refund_id)
        if not refund:
            raise NotFoundError(f"Refund with id {command.refund_id} not found")

        refund.ensure_pending("complete")
        before_status = refund.status

        # It may have changed since the refund was created: cancelled, or
        # invoiced after a resend
        sale = self.sale_repo.get_by_id(refund.original_sale_id)
        if sale is None or not sale.is_completed:
            raise SaleNotConfirmedError(refund.original_sale_id)
        if sale.invoiced_to_final_consumer and not command.final_consumer_allowed:
            raise FinalConsumerRefundNotAllowedError(refund.original_sale_id)

        items = self.refund_item_repo.filter_by(refund_id=command.refund_id)

        methods = [self._payment_method(p["payment_method"]) for p in command.payments]
        if PaymentMethod.CREDIT in methods:
            # What goes to the account is the core's to decide, below
            raise CreditPaymentNotAllowedError()

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
            # At the cost the sale took it out at (S5.6)
            costs=self.stock.costs_of("sale", sale.require_id()),
        )

        # A sale on credit takes the refund off its receivable first (S5.5):
        # only what exceeds its balance is given back in money
        credited = self.credit.credit_refund(sale, refund.require_id(), refund.total)
        total_payment = round_money(
            sum((Decimal(str(p["amount"])) for p in command.payments), Decimal("0"))
        )
        if credited > Decimal("0"):
            due = refund.total - credited
            if total_payment != due:
                raise ValidationError(
                    message=(
                        f"{credited} of the refund goes to the customer's account: "
                        f"the payments must give back {due}"
                    ),
                    detail=f"Total: {refund.total}, credited: {credited}, paid: "
                    f"{total_payment}",
                )
        elif total_payment < refund.total:
            raise ValidationError(
                message="Payment amount is insufficient",
                detail=f"Total: {refund.total}, paid: {total_payment}",
            )

        created_payments = []
        if credited > Decimal("0"):
            created_payments.append(
                self.refund_payment_repo.create(
                    RefundPayment(
                        refund_id=refund.require_id(),
                        amount=credited,
                        payment_method=PaymentMethod.CREDIT,
                    )
                )
            )
        for payment_data, payment_method in zip(command.payments, methods, strict=True):
            payment = RefundPayment(
                refund_id=refund.require_id(),
                amount=Decimal(str(payment_data["amount"])),
                payment_method=payment_method,
                reference=payment_data.get("reference"),
            )
            payment = self.refund_payment_repo.create(payment)
            created_payments.append(payment)

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
            ),
            # Its credit note, if it needs one, goes to the outbox in this transaction
            session=self.session,
        )

        result = refund.dict()
        notes = self.credit_notes.of_refunds([refund.require_id()])
        result["credit_note"] = notes[0].dict() if notes else None
        result["items"] = [{**item.dict(), "subtotal": item.subtotal} for item in items]
        result["payments"] = [p.dict() for p in created_payments]
        result["account_credit"] = credited
        return result

    @staticmethod
    def _payment_method(value: str) -> PaymentMethod:
        try:
            return PaymentMethod(value)
        except ValueError:
            raise ValidationError(
                message=f"Invalid payment method: {value}",
                detail=f"Valid methods: {[m.value for m in PaymentMethod]}",
            ) from None
