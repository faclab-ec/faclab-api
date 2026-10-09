from src.shared.domain.exceptions import AlreadyExistsError


class LotAlreadyExistsError(AlreadyExistsError):
    error_code = "LOT_ALREADY_EXISTS"

    def __init__(self, lot_number: str | None = None, product_id: int | None = None):
        if lot_number is None:
            message = "A lot with this number already exists for the product"
        else:
            message = f"Lot '{lot_number}' already exists for product {product_id}."
        super().__init__(message)
