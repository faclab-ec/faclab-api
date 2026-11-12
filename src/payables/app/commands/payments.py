from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from wireup import injectable

from src.organization.app.numbering import DocumentNumbering
from src.organization.domain.numbering import DocumentType
from src.payables.app.repositories import (
    PayableApplicationRepository,
    PayableRepository,
    SupplierPaymentRepository,
)
from src.payables.domain.allocation import allocate_fifo, allocate_manual
from src.payables.domain.entities import (
    PayableApplication,
    PayableApplicationKind,
    SupplierPayment,
)
from src.sales.domain.entities import PaymentMethod
from src.shared.app.audit import AuditAction, AuditTrail
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError, ValidationError
from src.suppliers.app.repositories import SupplierRepository


@dataclass
class RecordSupplierPaymentCommand(Command):
    """Un pago al proveedor. Sin `applications` se aplica FIFO (la cuenta que
    vence antes primero); con ellas, a cada cuenta lo que dicen."""

    supplier_id: int
    amount: Decimal
    payment_method: str
    reference: str | None = None
    notes: str | None = None
    # [{"payable_id": int, "amount": Decimal}]
    applications: list[dict] | None = None
    paid_by: str | None = None


@injectable(lifetime="scoped")
class RecordSupplierPaymentCommandHandler(
    CommandHandler[RecordSupplierPaymentCommand, dict]
):
    """Bloquea las cuentas abiertas del proveedor (en orden de id): dos pagos o
    un pago y una devolución del mismo proveedor se turnan. Numera el pago al
    final, con el contador de la empresa."""

    def __init__(
        self,
        suppliers: SupplierRepository,
        payables: PayableRepository,
        applications: PayableApplicationRepository,
        payments: SupplierPaymentRepository,
        numbering: DocumentNumbering,
        audit: AuditTrail,
    ):
        self.suppliers = suppliers
        self.payables = payables
        self.applications = applications
        self.payments = payments
        self.numbering = numbering
        self.audit = audit

    def _handle(self, command: RecordSupplierPaymentCommand) -> dict:
        payment = SupplierPayment(
            supplier_id=command.supplier_id,
            amount=Decimal(str(command.amount)),
            payment_method=_payment_method(command.payment_method),
            reference=command.reference,
            notes=command.notes,
            paid_by=command.paid_by,
        )
        supplier = self.suppliers.get_by_id(command.supplier_id)
        if supplier is None:
            raise NotFoundError(f"Supplier with id {command.supplier_id} not found")

        payables = self.payables.open_for_update(command.supplier_id)
        if command.applications:
            allocations = allocate_manual(
                payment.amount,
                payables,
                {
                    int(a["payable_id"]): Decimal(str(a["amount"]))
                    for a in command.applications
                },
            )
        else:
            allocations = allocate_fifo(payment.amount, payables)

        payment.number = self.numbering.next_in_tenant(
            DocumentType.SUPPLIER_PAYMENT, date.today().year
        )
        payment = self.payments.create(payment)

        applied = []
        for allocation in allocations:
            payable = allocation.payable
            payable.credit(allocation.amount)
            self.payables.update(payable)
            self.applications.create(
                PayableApplication(
                    payable_id=payable.require_id(),
                    amount=allocation.amount,
                    kind=PayableApplicationKind.PAYMENT,
                    supplier_payment_id=payment.require_id(),
                )
            )
            applied.append(
                {
                    "payable_id": payable.require_id(),
                    "purchase_order_id": payable.purchase_order_id,
                    "supplier_invoice_number": payable.supplier_invoice_number,
                    "amount": allocation.amount,
                    "balance": payable.balance,
                }
            )

        self.audit.record(
            AuditAction.SUPPLIER_PAYMENT_RECORDED,
            payment.require_id(),
            after={
                "number": payment.number,
                "supplier_id": payment.supplier_id,
                "amount": payment.amount,
                "payment_method": payment.payment_method,
                "applications": [
                    {"payable_id": a["payable_id"], "amount": a["amount"]}
                    for a in applied
                ],
            },
        )
        return {
            **payment.dict(),
            "supplier_name": supplier.name,
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
