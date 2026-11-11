from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from wireup import injectable

from src.customers.app.repositories import CustomerRepository
from src.organization.app.numbering import DocumentNumbering
from src.organization.domain.numbering import DocumentType
from src.pos.shift.app.repositories import ShiftRepository
from src.pos.shift.domain.exceptions import NoOpenShiftError
from src.pos.terminal.app.resolver import TerminalRequest, TerminalResolver
from src.receivables.app.repositories import (
    CustomerPaymentRepository,
    ReceivableApplicationRepository,
    ReceivableRepository,
)
from src.receivables.domain.allocation import allocate_fifo, allocate_manual
from src.receivables.domain.entities import (
    CustomerPayment,
    ReceivableApplication,
    ReceivableApplicationKind,
)
from src.sales.app.repositories import SaleRepository
from src.sales.domain.entities import PaymentMethod
from src.shared.app.audit import AuditAction, AuditTrail
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError, ValidationError


@dataclass
class RecordCustomerPaymentCommand(Command):
    """Un abono del cliente. Sin `applications` se aplica FIFO (la cuenta que
    vence antes primero); con ellas, a cada cuenta lo que dicen. En el POS
    (`terminal`) entra en la caja del turno abierto de la terminal."""

    customer_id: int
    amount: Decimal
    payment_method: str
    reference: str | None = None
    notes: str | None = None
    # [{"receivable_id": int, "amount": Decimal}]
    applications: list[dict] | None = None
    received_by: str | None = None
    # Outside the cash register: the branch of the request, if any
    branch_id: int | None = None
    terminal: TerminalRequest | None = None


@injectable(lifetime="scoped")
class RecordCustomerPaymentCommandHandler(
    CommandHandler[RecordCustomerPaymentCommand, dict]
):
    """Bloquea al cliente y luego sus cuentas abiertas (en orden de id), como la
    venta a crédito, que también bloquea al cliente: un abono y una venta del
    mismo cliente se turnan. Numera el abono al final, con el contador de la
    empresa."""

    def __init__(
        self,
        customers: CustomerRepository,
        receivables: ReceivableRepository,
        applications: ReceivableApplicationRepository,
        payments: CustomerPaymentRepository,
        sales: SaleRepository,
        terminals: TerminalResolver,
        shifts: ShiftRepository,
        numbering: DocumentNumbering,
        audit: AuditTrail,
    ):
        self.customers = customers
        self.receivables = receivables
        self.applications = applications
        self.payments = payments
        self.sales = sales
        self.terminals = terminals
        self.shifts = shifts
        self.numbering = numbering
        self.audit = audit

    def _handle(self, command: RecordCustomerPaymentCommand) -> dict:
        payment = CustomerPayment(
            customer_id=command.customer_id,
            amount=Decimal(str(command.amount)),
            payment_method=_payment_method(command.payment_method),
            reference=command.reference,
            notes=command.notes,
            received_by=command.received_by,
            branch_id=command.branch_id,
        )
        if command.terminal is not None:
            # At the POS: in the cash of the terminal's open shift
            terminal = self.terminals.terminal(command.terminal)
            shift = self.shifts.first(terminal_id=terminal.id, status="OPEN")
            if shift is None:
                raise NoOpenShiftError()
            payment.terminal_id = terminal.id
            payment.branch_id = terminal.branch_id
            payment.shift_id = shift.id

        customer = self.customers.first_for_update(id=command.customer_id)
        if customer is None:
            raise NotFoundError(f"Customer with id {command.customer_id} not found")
        receivables = self.receivables.open_for_update(command.customer_id)
        if command.applications:
            allocations = allocate_manual(
                payment.amount,
                receivables,
                {
                    int(a["receivable_id"]): Decimal(str(a["amount"]))
                    for a in command.applications
                },
            )
        else:
            allocations = allocate_fifo(payment.amount, receivables)

        payment.number = self.numbering.next_in_tenant(
            DocumentType.CUSTOMER_PAYMENT, date.today().year
        )
        payment = self.payments.create(payment)

        applied = []
        sales = {
            sale.require_id(): sale
            for sale in self.sales.get_by_ids(a.receivable.sale_id for a in allocations)
        }
        for allocation in allocations:
            receivable = allocation.receivable
            receivable.credit(allocation.amount)
            self.receivables.update(receivable)
            self.applications.create(
                ReceivableApplication(
                    receivable_id=receivable.require_id(),
                    amount=allocation.amount,
                    kind=ReceivableApplicationKind.PAYMENT,
                    customer_payment_id=payment.require_id(),
                )
            )
            sale = sales.get(receivable.sale_id)
            if sale is not None:
                # Paid once its receivable is
                sale.owe_on_account(receivable.balance)
                self.sales.update(sale)
            applied.append(
                {
                    "receivable_id": receivable.require_id(),
                    "sale_id": receivable.sale_id,
                    "sale_number": sale.number if sale else None,
                    "amount": allocation.amount,
                    "balance": receivable.balance,
                }
            )

        self.audit.record(
            AuditAction.CUSTOMER_PAYMENT_RECORDED,
            payment.require_id(),
            after={
                "number": payment.number,
                "customer_id": payment.customer_id,
                "amount": payment.amount,
                "payment_method": payment.payment_method,
                "shift_id": payment.shift_id,
                "applications": [
                    {"receivable_id": a["receivable_id"], "amount": a["amount"]}
                    for a in applied
                ],
            },
            branch_id=payment.branch_id,
        )
        return {
            **payment.dict(),
            "customer_name": customer.name,
            "applications": applied,
        }


def _payment_method(value: str) -> PaymentMethod:
    try:
        return PaymentMethod(value)
    except ValueError:
        raise ValidationError(
            message=f"Invalid payment method: {value}",
            detail=f"Valid methods: {[m.value for m in PaymentMethod]}",
        ) from None
