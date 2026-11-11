"""Excepciones de las cuentas por cobrar (S5.5)"""

from decimal import Decimal

from src.shared.domain.exceptions import DomainError, ValidationError


class CustomerWithoutCreditError(DomainError):
    """El cliente no compra a crédito: está inactivo o no tiene cupo"""

    error_code = "CUSTOMER_WITHOUT_CREDIT"

    def __init__(self, customer_id: int):
        self.customer_id = customer_id
        super().__init__(
            message=(
                f"Customer {customer_id} cannot buy on credit: it is inactive or "
                "has no credit limit"
            ),
            detail=f"customer_id={customer_id}",
        )


class CreditLimitExceededError(DomainError):
    """Lo que debe más el crédito nuevo supera su cupo"""

    error_code = "CREDIT_LIMIT_EXCEEDED"

    def __init__(
        self, customer_id: int, limit: Decimal, outstanding: Decimal, amount: Decimal
    ):
        self.customer_id = customer_id
        self.limit = limit
        self.outstanding = outstanding
        self.amount = amount
        available = max(limit - outstanding, Decimal("0"))
        super().__init__(
            message=(
                f"A credit of {amount} exceeds the credit limit of customer "
                f"{customer_id}: it owes {outstanding} of {limit}, "
                f"{available} available"
            ),
            detail=(
                f"credit_limit={limit}, outstanding={outstanding}, "
                f"available={available}, amount={amount}"
            ),
        )


class ReceivableNotOpenError(DomainError):
    """La cuenta ya está pagada o anulada, o no es del cliente"""

    error_code = "RECEIVABLE_NOT_OPEN"

    def __init__(self, receivable_id: int | None):
        self.receivable_id = receivable_id
        super().__init__(
            message=f"Receivable {receivable_id} is not open for this customer",
            detail=f"receivable_id={receivable_id}",
        )


class ReceivableHasPaymentsError(DomainError):
    """Una venta a crédito con abonos o devoluciones acreditadas no se anula:
    se devuelve"""

    error_code = "RECEIVABLE_HAS_PAYMENTS"

    def __init__(self, sale_id: int):
        self.sale_id = sale_id
        super().__init__(
            message=(
                f"Sale {sale_id} has payments on its account: refund it instead "
                "of cancelling it"
            ),
            detail=f"sale_id={sale_id}",
        )


class CustomerPaymentExceedsBalanceError(DomainError):
    """El abono supera lo que el cliente debe: no queda saldo a favor"""

    error_code = "CUSTOMER_PAYMENT_EXCEEDS_BALANCE"

    def __init__(self, amount: Decimal, owed: Decimal):
        self.amount = amount
        self.owed = owed
        super().__init__(
            message=f"A payment of {amount} exceeds what the customer owes: {owed}",
            detail=f"amount={amount}, owed={owed}",
        )


class PaymentApplicationMismatchError(ValidationError):
    """La aplicación manual no suma el abono, o pasa el saldo de una cuenta"""

    error_code = "PAYMENT_APPLICATION_MISMATCH"


class CreditPaymentNotAllowedError(ValidationError):
    """Un abono o una devolución no se pagan con CREDIT: lo que va a la cuenta
    del cliente lo decide el core"""

    error_code = "CREDIT_PAYMENT_NOT_ALLOWED"

    def __init__(self):
        super().__init__(message="This payment cannot be made with CREDIT")
