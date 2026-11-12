from datetime import date
from decimal import Decimal

from wireup import injectable

from src.payables.app.repositories import (
    PayableApplicationRepository,
    PayableRepository,
)
from src.payables.domain.allocation import allocate_return
from src.payables.domain.entities import (
    Payable,
    PayableApplication,
    PayableApplicationKind,
)
from src.shared.domain.exceptions import NotFoundError
from src.suppliers.app.repositories import SupplierRepository

ZERO = Decimal("0")


@injectable(lifetime="scoped")
class SupplierAccounts:
    """Las cuentas por pagar de los proveedores (S5.7), en la transacción de la
    recepción o de la devolución que las mueve: compras las compone como el POS
    compone el crédito de los clientes.

    `open_for_receipt` abre la cuenta de lo recibido, con el plazo del
    proveedor. `credit_return` acredita una devolución a sus cuentas abiertas
    después de que la devolución bloqueó las líneas de la orden y el stock: el
    orden es líneas de la orden → stock → cuentas por pagar, como en la
    recepción, y un pago solo bloquea cuentas.
    """

    def __init__(
        self,
        suppliers: SupplierRepository,
        payables: PayableRepository,
        applications: PayableApplicationRepository,
    ):
        self.suppliers = suppliers
        self.payables = payables
        self.applications = applications

    def open_for_receipt(
        self,
        *,
        supplier_id: int,
        purchase_order_id: int,
        purchase_receipt_id: int,
        amount: Decimal,
        issued_on: date,
        supplier_invoice_number: str | None = None,
    ) -> Payable | None:
        """La cuenta de una recepción, si recibió algo con costo: vence en el
        plazo del proveedor (sin plazo, el mismo día)"""
        if amount <= ZERO:
            return None
        supplier = self.suppliers.get_by_id(supplier_id)
        if supplier is None:
            raise NotFoundError(f"Supplier with id {supplier_id} not found")
        return self.payables.create(
            Payable.open(
                supplier_id=supplier_id,
                purchase_order_id=purchase_order_id,
                purchase_receipt_id=purchase_receipt_id,
                amount=amount,
                term_days=supplier.payment_terms or 0,
                issued_on=issued_on,
                supplier_invoice_number=supplier_invoice_number,
            )
        )

    def credit_return(
        self,
        *,
        supplier_id: int,
        purchase_order_id: int,
        supplier_return_id: int,
        amount: Decimal,
    ) -> Decimal:
        """Acredita una devolución a las cuentas abiertas del proveedor (primero
        las de su orden) y dice cuánto acreditó: el resto lo reembolsa el
        proveedor, que ya había cobrado"""
        if amount <= ZERO:
            return ZERO
        allocations = allocate_return(
            amount, self.payables.open_for_update(supplier_id), purchase_order_id
        )
        credited = ZERO
        for allocation in allocations:
            payable = allocation.payable
            payable.credit(allocation.amount)
            self.payables.update(payable)
            self.applications.create(
                PayableApplication(
                    payable_id=payable.require_id(),
                    amount=allocation.amount,
                    kind=PayableApplicationKind.RETURN,
                    supplier_return_id=supplier_return_id,
                )
            )
            credited += allocation.amount
        return credited
