from src.shared.domain.exceptions import (
    AlreadyExistsError,
    DomainError,
    InvalidValueError,
)


class PriceListNameAlreadyExistsError(AlreadyExistsError):
    error_code = "PRICE_LIST_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("A price list with this name already exists")


class PriceListItemAlreadyExistsError(AlreadyExistsError):
    """Una lista tiene un solo precio por presentación y cantidad mínima"""

    error_code = "PRICE_LIST_ITEM_ALREADY_EXISTS"

    def __init__(self):
        super().__init__(
            "The price list already has a price for this presentation from this "
            "quantity"
        )


class InvalidPriceListValidityError(InvalidValueError):
    def __init__(self):
        super().__init__("A price list can't end before it starts")


class InvalidPriceListItemError(InvalidValueError):
    pass


class DefaultPriceListLockedError(DomainError):
    """La lista general siempre aplica: no se borra, no se desactiva ni tiene
    vigencia"""

    error_code = "DEFAULT_PRICE_LIST_LOCKED"

    def __init__(
        self,
        detail: str = "The general price list is always active and has no validity "
        "dates",
    ):
        super().__init__(detail)


class DefaultPriceListBasePriceError(DomainError):
    """El precio base de la lista general es el del producto: la lista solo
    guarda escalas por volumen"""

    error_code = "DEFAULT_PRICE_LIST_BASE_PRICE"

    def __init__(self):
        super().__init__(
            "The general price list only holds quantity tiers (a minimum quantity "
            "above zero): its base price is the product's"
        )
