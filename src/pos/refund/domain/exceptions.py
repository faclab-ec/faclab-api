from src.shared.domain.exceptions import DomainError


class RefundError(DomainError):
    error_code = "REFUND_ERROR"


class InvalidRefundStatusError(RefundError):
    error_code = "INVALID_REFUND_STATUS"

    def __init__(self, current_status: str, operation: str):
        self.current_status = current_status
        self.operation = operation
        super().__init__(
            message=f"Cannot {operation} refund with status {current_status}",
            detail=f"current_status={current_status}, operation={operation}",
        )


class ExceedsOriginalQuantityError(RefundError):
    error_code = "EXCEEDS_ORIGINAL_QUANTITY"

    def __init__(self, sale_item_id: int, requested: int, available: int):
        self.sale_item_id = sale_item_id
        self.requested = requested
        self.available = available
        super().__init__(
            message=(
                f"Refund quantity {requested} exceeds remaining quantity "
                f"{available} for sale item {sale_item_id}"
            ),
            detail=(
                f"sale_item_id={sale_item_id}, "
                f"requested={requested}, available={available}"
            ),
        )


class SaleNotConfirmedError(RefundError):
    error_code = "SALE_NOT_CONFIRMED"

    def __init__(self, sale_id: int):
        self.sale_id = sale_id
        super().__init__(
            message=f"Sale {sale_id} is not confirmed",
            detail=f"sale_id={sale_id}",
        )


class RefundItemNotInSaleError(RefundError):
    error_code = "REFUND_ITEM_NOT_IN_SALE"

    def __init__(self, sale_item_id: int, sale_id: int):
        self.sale_item_id = sale_item_id
        self.sale_id = sale_id
        super().__init__(
            message=f"Sale item {sale_item_id} does not belong to sale {sale_id}",
            detail=f"sale_item_id={sale_item_id}, sale_id={sale_id}",
        )


class RefundOutsideBranchError(RefundError):
    """A sale is refunded in a terminal of its own branch: its stock, cash and
    numbering stay there"""

    error_code = "REFUND_OUTSIDE_BRANCH"

    def __init__(self, sale_id: int):
        self.sale_id = sale_id
        super().__init__(
            message=f"Sale {sale_id} was made in another branch",
            detail=f"sale_id={sale_id}",
        )
