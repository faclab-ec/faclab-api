from decimal import Decimal

from src.shared.domain.exceptions import AlreadyExistsError, DomainError
from src.shared.domain.quantity import format_quantity


class InvalidPurchaseOrderStatusError(DomainError):
    error_code = "INVALID_PURCHASE_ORDER_STATUS"

    def __init__(self, current_status: str, operation: str):
        self.current_status = current_status
        self.operation = operation
        super().__init__(
            message=f"Cannot {operation} a purchase order with status '{current_status}'",
            detail=f"current_status={current_status}, operation={operation}",
        )


class ExceedsPendingQuantityError(DomainError):
    error_code = "EXCEEDS_PENDING_QUANTITY"

    def __init__(
        self,
        purchase_order_item_id: int,
        requested: Decimal | int,
        pending: Decimal | int,
    ):
        self.purchase_order_item_id = purchase_order_item_id
        self.requested = requested
        self.pending = pending
        requested_text = format_quantity(requested)
        pending_text = format_quantity(pending)
        super().__init__(
            message=(
                f"Cannot receive {requested_text} units for item "
                f"{purchase_order_item_id}. Only {pending_text} units are pending."
            ),
            detail=(
                f"purchase_order_item_id={purchase_order_item_id}, "
                f"requested={requested_text}, pending={pending_text}"
            ),
        )


class PurchaseOrderNumberAlreadyExistsError(AlreadyExistsError):
    error_code = "PURCHASE_ORDER_NUMBER_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("A purchase order with this number already exists")


class ExceedsReturnableQuantityError(DomainError):
    """Se devuelve más de lo recibido menos lo ya devuelto (S5.7)"""

    error_code = "EXCEEDS_RETURNABLE_QUANTITY"

    def __init__(
        self,
        purchase_order_item_id: int,
        requested: Decimal | int,
        returnable: Decimal | int,
    ):
        self.purchase_order_item_id = purchase_order_item_id
        self.requested = requested
        self.returnable = returnable
        requested_text = format_quantity(requested)
        returnable_text = format_quantity(returnable)
        super().__init__(
            message=(
                f"Cannot return {requested_text} units of item "
                f"{purchase_order_item_id}. Only {returnable_text} units can be returned."
            ),
            detail=(
                f"purchase_order_item_id={purchase_order_item_id}, "
                f"requested={requested_text}, returnable={returnable_text}"
            ),
        )


class InvalidSupplierReturnStatusError(DomainError):
    error_code = "INVALID_SUPPLIER_RETURN_STATUS"

    def __init__(self, current_status: str, operation: str):
        self.current_status = current_status
        self.operation = operation
        super().__init__(
            message=f"Cannot {operation} a supplier return with status '{current_status}'",
            detail=f"current_status={current_status}, operation={operation}",
        )


class PurchaseOrderNotReturnableError(DomainError):
    """La orden no tiene nada recibido que se pueda devolver"""

    error_code = "PURCHASE_ORDER_NOT_RETURNABLE"

    def __init__(self, order_number: str):
        self.order_number = order_number
        super().__init__(
            message=f"Purchase order {order_number} has nothing received to return",
            detail=f"order_number={order_number}",
        )


class SupplierReturnItemOutsideOrderError(DomainError):
    """La línea de la orden no es de la orden de la devolución"""

    error_code = "SUPPLIER_RETURN_ITEM_OUTSIDE_ORDER"

    def __init__(self, purchase_order_item_id: int, purchase_order_id: int):
        super().__init__(
            message=(
                f"Purchase order item {purchase_order_item_id} is not of purchase "
                f"order {purchase_order_id}"
            ),
            detail=(
                f"purchase_order_item_id={purchase_order_item_id}, "
                f"purchase_order_id={purchase_order_id}"
            ),
        )


class EmptySupplierReturnError(DomainError):
    error_code = "SUPPLIER_RETURN_WITHOUT_ITEMS"

    def __init__(self, number: str | None):
        super().__init__(
            message=f"Supplier return {number} has no items",
            detail=f"number={number}",
        )


class SupplierReturnCreditExceedsTotalError(DomainError):
    error_code = "SUPPLIER_RETURN_CREDIT_EXCEEDS_TOTAL"

    def __init__(self, credited: Decimal, total: Decimal):
        super().__init__(
            message=f"Cannot credit {credited} of a supplier return of {total}",
            detail=f"credited={credited}, total={total}",
        )


class SupplierReturnNumberAlreadyExistsError(AlreadyExistsError):
    error_code = "SUPPLIER_RETURN_NUMBER_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("A supplier return with this number already exists")
