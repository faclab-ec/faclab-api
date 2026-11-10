from decimal import Decimal

from src.shared.domain.exceptions import DomainError
from src.shared.domain.quantity import format_quantity


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

    def __init__(
        self, sale_item_id: int, requested: Decimal | int, available: Decimal | int
    ):
        self.sale_item_id = sale_item_id
        self.requested = requested
        self.available = available
        requested_text = format_quantity(requested)
        available_text = format_quantity(available)
        super().__init__(
            message=(
                f"Refund quantity {requested_text} exceeds remaining quantity "
                f"{available_text} for sale item {sale_item_id}"
            ),
            detail=(
                f"sale_item_id={sale_item_id}, "
                f"requested={requested_text}, available={available_text}"
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


class FinalConsumerRefundNotAllowedError(RefundError):
    """La factura a consumidor final no se anula ni admite nota de crédito
    (NAC-DGERCGC25-00000014, art. 3, desde el 01/01/2026), así que esa devolución no
    tendría respaldo tributario. FINAL_CONSUMER_REFUNDS_ALLOWED la permite."""

    error_code = "FINAL_CONSUMER_REFUND_NOT_ALLOWED"

    def __init__(self, sale_id: int):
        self.sale_id = sale_id
        super().__init__(
            message=(
                f"Sale {sale_id} was invoiced to the final consumer: its invoice "
                "doesn't admit a credit note, so it can't be refunded"
            ),
            detail="NAC-DGERCGC25-00000014, art. 3",
        )


class RefundReasonRequiredError(RefundError):
    """La devolución de una venta con factura genera una nota de crédito, y su
    XML exige el motivo"""

    error_code = "REFUND_REASON_REQUIRED"

    def __init__(self, sale_id: int):
        self.sale_id = sale_id
        super().__init__(
            message=f"Sale {sale_id} has an invoice: a refund of it needs a reason",
            detail=f"sale_id={sale_id}",
        )
