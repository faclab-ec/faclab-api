from src.shared.domain.exceptions import AlreadyExistsError, DomainError


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

    def __init__(self, purchase_order_item_id: int, requested: int, pending: int):
        self.purchase_order_item_id = purchase_order_item_id
        self.requested = requested
        self.pending = pending
        super().__init__(
            message=(
                f"Cannot receive {requested} units for item {purchase_order_item_id}. "
                f"Only {pending} units are pending."
            ),
            detail=(
                f"purchase_order_item_id={purchase_order_item_id}, "
                f"requested={requested}, pending={pending}"
            ),
        )


class PurchaseOrderNumberAlreadyExistsError(AlreadyExistsError):
    error_code = "PURCHASE_ORDER_NUMBER_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("A purchase order with this number already exists")
