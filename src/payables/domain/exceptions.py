"""Excepciones de las cuentas por pagar (S5.7)"""

from decimal import Decimal

from src.shared.domain.exceptions import DomainError, ValidationError


class PayableNotOpenError(DomainError):
    """La cuenta ya está pagada, o no es del proveedor"""

    error_code = "PAYABLE_NOT_OPEN"

    def __init__(self, payable_id: int | None):
        self.payable_id = payable_id
        super().__init__(
            message=f"Payable {payable_id} is not open for this supplier",
            detail=f"payable_id={payable_id}",
        )


class SupplierPaymentExceedsBalanceError(DomainError):
    """El pago supera lo que se le debe al proveedor: no queda saldo a favor"""

    error_code = "SUPPLIER_PAYMENT_EXCEEDS_BALANCE"

    def __init__(self, amount: Decimal, owed: Decimal):
        self.amount = amount
        self.owed = owed
        super().__init__(
            message=f"A payment of {amount} exceeds what is owed to the supplier: {owed}",
            detail=f"amount={amount}, owed={owed}",
        )


class SupplierPaymentApplicationMismatchError(ValidationError):
    """La aplicación manual no suma el pago, o pasa el saldo de una cuenta"""

    error_code = "SUPPLIER_PAYMENT_APPLICATION_MISMATCH"


class CreditPaymentNotAllowedError(ValidationError):
    """Un pago a proveedor no se hace con CREDIT"""

    error_code = "CREDIT_PAYMENT_NOT_ALLOWED"

    def __init__(self):
        super().__init__(message="A supplier payment cannot be made with CREDIT")
