"""Excepciones específicas del dominio de Sales"""

from decimal import Decimal

from src.shared.domain.exceptions import DomainError


class SalesError(DomainError):
    """Excepción base para el dominio de sales"""

    error_code = "SALES_ERROR"


class InvalidSaleStatusError(SalesError):
    """Se lanza cuando se intenta realizar una operación con un estado inválido"""

    error_code = "INVALID_SALE_STATUS"

    def __init__(self, current_status: str, operation: str):
        self.current_status = current_status
        self.operation = operation
        super().__init__(
            message=f"Cannot {operation} sale with status {current_status}",
            detail=f"current_status={current_status}, operation={operation}",
        )


class SaleHasNoItemsError(SalesError):
    """Se lanza cuando se intenta confirmar una venta sin items"""

    error_code = "SALE_HAS_NO_ITEMS"

    def __init__(self, sale_id: int):
        self.sale_id = sale_id
        super().__init__(
            message=f"Sale {sale_id} has no items",
            detail=f"sale_id={sale_id}",
        )


class SaleNotParkedError(SalesError):
    """Se lanza cuando se intenta retomar una venta que no está aparcada"""

    error_code = "SALE_NOT_PARKED"

    def __init__(self, sale_id: int | None):
        self.sale_id = sale_id
        super().__init__(
            message=f"Sale {sale_id} is not parked",
            detail=f"sale_id={sale_id}",
        )


class InsufficientStockError(SalesError):
    """Se lanza cuando no hay suficiente stock para confirmar una venta"""

    error_code = "INSUFFICIENT_STOCK"

    def __init__(self, product_id: int, requested: int, available: int):
        self.product_id = product_id
        self.requested = requested
        self.available = available
        super().__init__(
            message=(
                f"Insufficient stock for product {product_id}. "
                f"Requested: {requested}, Available: {available}"
            ),
            detail=f"product_id={product_id}, requested={requested}, available={available}",
        )


class SaleItemNotInSaleError(SalesError):
    """Se lanza cuando un item no pertenece a la venta indicada"""

    error_code = "SALE_ITEM_NOT_IN_SALE"

    def __init__(self, sale_item_id: int, sale_id: int):
        self.sale_item_id = sale_item_id
        self.sale_id = sale_id
        super().__init__(
            message=f"Sale item {sale_item_id} does not belong to sale {sale_id}",
            detail=f"sale_item_id={sale_item_id}, sale_id={sale_id}",
        )


class CustomerRequiredError(SalesError):
    """Se lanza cuando una venta que no es a consumidor final no tiene cliente"""

    error_code = "CUSTOMER_REQUIRED"

    def __init__(self):
        super().__init__(
            message="customer_id is required when is_final_consumer is False"
        )


class OverrideReasonRequiredError(SalesError):
    """Se lanza cuando se vende un item a otro precio sin indicar el motivo"""

    error_code = "OVERRIDE_REASON_REQUIRED"

    def __init__(self, product_id: int):
        self.product_id = product_id
        super().__init__(
            message="A reason is required to sell below or above the list price",
            detail=f"product_id={product_id}",
        )


class SaleWithoutEmissionPointError(SalesError):
    """La venta no tiene punto de emisión (anterior a S2.6): faclab-invoicing no
    sabe con qué establecimiento ni con qué secuencial facturarla"""

    error_code = "SALE_WITHOUT_EMISSION_POINT"

    def __init__(self, sale_id: int):
        self.sale_id = sale_id
        super().__init__(
            message=f"Sale {sale_id} has no emission point and cannot be invoiced",
            detail=f"sale_id={sale_id}",
        )


class SaleNotPayableError(SalesError):
    """Una venta cancelada o facturada no recibe pagos"""

    error_code = "SALE_NOT_PAYABLE"

    def __init__(self, sale_id: int | None, status: str):
        self.sale_id = sale_id
        self.status = status
        super().__init__(
            message=f"Sale {sale_id} is {status} and cannot take payments",
            detail=f"sale_id={sale_id}, status={status}",
        )


class PaymentExceedsBalanceError(SalesError):
    """El pago no aplica nada a la venta, o no es en efectivo y supera lo que
    falta pagar: solo el efectivo deja vuelto"""

    error_code = "PAYMENT_EXCEEDS_BALANCE"

    def __init__(self, tendered: Decimal, owed: Decimal, payment_method: str):
        self.tendered = tendered
        self.owed = owed
        self.payment_method = payment_method
        super().__init__(
            message=(
                f"A {payment_method} payment of {tendered} exceeds the balance "
                f"of {owed}; only cash can be handed over in excess"
            ),
            detail=f"tendered={tendered}, owed={owed}, payment_method={payment_method}",
        )


class InsufficientPaymentError(SalesError):
    """Los pagos no cubren el total de la venta"""

    error_code = "INSUFFICIENT_PAYMENT"

    def __init__(self, sale_id: int | None, total: Decimal, paid: Decimal):
        self.sale_id = sale_id
        self.total = total
        self.paid = paid
        super().__init__(
            message=f"Payments of sale {sale_id} do not cover its total",
            detail=f"total={total}, paid={paid}",
        )


class InvoiceInProgressError(SalesError):
    """La factura de la venta está en faclab-invoicing sin resultado: anularla
    ahora podría dejar una factura autorizada sin venta que la respalde"""

    error_code = "INVOICE_IN_PROGRESS"

    def __init__(self, sale_id: int | None):
        self.sale_id = sale_id
        super().__init__(
            message=(
                f"Sale {sale_id} cannot be cancelled while its invoice is in "
                "progress; wait for the SRI's answer"
            ),
            detail=f"sale_id={sale_id}",
        )


class CreditNoteRequiredError(SalesError):
    """Una venta facturada no se anula: se anula con una nota de crédito (S4.5)"""

    error_code = "CREDIT_NOTE_REQUIRED"

    def __init__(self, sale_id: int | None):
        self.sale_id = sale_id
        super().__init__(
            message=f"Sale {sale_id} is invoiced: void it with a credit note",
            detail=f"sale_id={sale_id}",
        )
