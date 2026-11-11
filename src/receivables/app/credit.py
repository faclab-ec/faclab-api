from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from wireup import injectable

from src.customers.app.repositories import CustomerRepository
from src.receivables.app.repositories import (
    ReceivableApplicationRepository,
    ReceivableRepository,
)
from src.receivables.domain.entities import (
    Receivable,
    ReceivableApplication,
    ReceivableApplicationKind,
)
from src.receivables.domain.exceptions import (
    CreditLimitExceededError,
    CustomerWithoutCreditError,
)
from src.sales.app.repositories import SaleRepository
from src.sales.domain.entities import Payment, PaymentMethod, Sale
from src.sales.domain.exceptions import CreditCustomerRequiredError
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.money import round_money


def credit_of(payments: Iterable[Payment]) -> Decimal:
    """Lo que los pagos de una venta dejan a crédito"""
    return sum(
        (p.amount for p in payments if p.payment_method == PaymentMethod.CREDIT),
        Decimal("0"),
    )


@injectable(lifetime="scoped")
class CustomerCredit:
    """El crédito de los clientes en las ventas del POS (S5.5), en la transacción
    de la venta, la devolución o la anulación.

    `open` bloquea la fila del cliente y comprueba su cupo (lo que debe más el
    crédito nuevo, hasta su límite): dos ventas a crédito simultáneas del mismo
    cliente se turnan y la segunda ve la cuenta de la primera. Se llama después
    de bloquear el stock y antes del contador, como todo documento del POS.

    Una devolución se acredita primero a la cuenta de su venta (`credit_refund`)
    y una venta a crédito se anula solo si su cuenta no bajó (`cancel_for_sale`).
    """

    def __init__(
        self,
        customers: CustomerRepository,
        receivables: ReceivableRepository,
        applications: ReceivableApplicationRepository,
        sales: SaleRepository,
    ):
        self.customers = customers
        self.receivables = receivables
        self.applications = applications
        self.sales = sales

    def open(self, sale: Sale, payments: list[Payment]) -> Receivable | None:
        """Abre la cuenta de lo que la venta deja a crédito, si deja algo: con el
        plazo del cliente en sus pagos CREDIT y la venta pendiente de cobro"""
        credit = credit_of(payments)
        if credit <= Decimal("0"):
            return None
        if sale.customer_id is None:
            raise CreditCustomerRequiredError(sale.id)
        customer = self.customers.first_for_update(id=sale.customer_id)
        if customer is None:
            raise NotFoundError(f"Customer with id {sale.customer_id} not found")
        customer_id = customer.id or sale.customer_id
        limit = customer.credit_limit
        if not customer.is_active or limit is None or limit <= Decimal("0"):
            raise CustomerWithoutCreditError(customer_id)
        outstanding = self.receivables.outstanding(customer_id)
        if outstanding + credit > limit:
            raise CreditLimitExceededError(customer_id, limit, outstanding, credit)

        term_days = customer.payment_terms or 0
        receivable = self.receivables.create(
            Receivable.open(
                customer_id=customer_id,
                sale_id=sale.require_id(),
                amount=credit,
                term_days=term_days,
                issued_on=date.today(),
                branch_id=sale.branch_id,
            )
        )
        for payment in payments:
            if payment.payment_method == PaymentMethod.CREDIT:
                payment.term_days = term_days
        sale.owe_on_account(receivable.balance)
        return receivable

    def creditable(self, sale_id: int, total: Decimal) -> Decimal:
        """Lo que una devolución de `total` acreditaría hoy a la cuenta de la
        venta (sin bloquearla): para mostrarlo antes de procesarla"""
        receivable = self.receivables.first(sale_id=sale_id)
        if receivable is None or not receivable.is_open:
            return Decimal("0")
        return min(round_money(total), receivable.balance)

    def credit_refund(self, sale: Sale, refund_id: int, total: Decimal) -> Decimal:
        """Acredita la devolución a la cuenta de su venta, hasta su saldo, y dice
        cuánto acreditó: el resto se devuelve en dinero"""
        receivable = self.receivables.first_for_update(sale_id=sale.require_id())
        if receivable is None or not receivable.is_open:
            return Decimal("0")
        amount = min(round_money(total), receivable.balance)
        if amount <= Decimal("0"):
            return Decimal("0")
        receivable.credit(amount)
        self.receivables.update(receivable)
        self.applications.create(
            ReceivableApplication(
                receivable_id=receivable.require_id(),
                amount=amount,
                kind=ReceivableApplicationKind.REFUND,
                refund_id=refund_id,
            )
        )
        sale.owe_on_account(receivable.balance)
        self.sales.update(sale)
        return amount

    def cancel_for_sale(self, sale_id: int) -> None:
        """Anula la cuenta de una venta que se anula: solo si nada bajó su saldo
        (con abonos o devoluciones, la venta se devuelve)"""
        receivable = self.receivables.first_for_update(sale_id=sale_id)
        if receivable is None:
            return
        receivable.cancel(
            has_applications=self.applications.count_by(
                receivable_id=receivable.require_id()
            )
            > 0
        )
        self.receivables.update(receivable)
