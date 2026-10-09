"""Excepciones específicas del dominio de Sales"""

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
