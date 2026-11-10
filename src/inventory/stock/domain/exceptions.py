from decimal import Decimal

from src.shared.domain.exceptions import DomainError
from src.shared.domain.quantity import format_quantity


class InsufficientStockError(DomainError):
    error_code = "INSUFFICIENT_STOCK"

    def __init__(self, product_id: int, quantity: Decimal | int):
        self.data = {"product_id": product_id, "quantity": quantity}
        quantity_text = format_quantity(quantity)
        super().__init__(
            message=f"Insufficient stock for product {product_id} with quantity {quantity_text}",
            detail=f"product_id={product_id}, quantity={quantity_text}",
        )
