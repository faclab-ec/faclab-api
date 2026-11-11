"""Excepciones de las cotizaciones (S5.4)"""

from datetime import date

from src.shared.domain.exceptions import ConflictError, DomainError, ValidationError


class InvalidQuoteStatusError(DomainError):
    error_code = "INVALID_QUOTE_STATUS"

    def __init__(self, current_status: str, operation: str):
        self.current_status = current_status
        self.operation = operation
        super().__init__(
            message=f"Cannot {operation} a quote with status {current_status}",
            detail=f"current_status={current_status}, operation={operation}",
        )


class QuoteExpiredError(DomainError):
    """Its validity ended: it has to be renewed first"""

    error_code = "QUOTE_EXPIRED"

    def __init__(self, number: str | None, valid_until: date):
        super().__init__(
            message=f"Quote {number} expired on {valid_until.isoformat()}: renew it "
            "to use it",
            detail=f"valid_until={valid_until.isoformat()}",
        )


class QuoteWithoutItemsError(DomainError):
    error_code = "QUOTE_WITHOUT_ITEMS"

    def __init__(self, number: str | None):
        super().__init__(message=f"Quote {number} has no items")


class QuoteItemsChangedError(DomainError):
    """The sale doesn't carry the quote's items: same products, presentations,
    quantities and discounts"""

    error_code = "QUOTE_ITEMS_CHANGED"

    def __init__(self, number: str | None):
        super().__init__(
            message=f"The sale's items are not those of quote {number}: sell its "
            "items as they are, or sell without the quote"
        )


class QuoteCustomerChangedError(DomainError):
    error_code = "QUOTE_CUSTOMER_CHANGED"

    def __init__(self, number: str | None):
        super().__init__(
            message=f"The sale's customer is not the one of quote {number}"
        )


class QuoteOutsideBranchError(DomainError):
    error_code = "QUOTE_OUTSIDE_BRANCH"

    def __init__(self, number: str | None):
        super().__init__(
            message=f"Quote {number} is of another branch: convert it at one of "
            "its terminals"
        )


class QuoteAlreadyConvertedError(ConflictError):
    error_code = "QUOTE_ALREADY_CONVERTED"

    def __init__(self, number: str | None = None):
        super().__init__(
            message=f"Quote {number} was already converted into a sale"
            if number
            else "The quote was already converted into a sale"
        )


class QuoteEmailRequiredError(ValidationError):
    """Nowhere to send it: no address given and the customer has none"""

    error_code = "QUOTE_EMAIL_REQUIRED"

    def __init__(self):
        super().__init__(
            message="Give the address to send the quote to: its customer has no email"
        )


class QuoteLineWithoutPriceError(DomainError):
    """Neither a list nor the product prices the line: a quote takes no price
    by hand, so the product needs one first"""

    error_code = "PRODUCT_WITHOUT_PRICE"

    def __init__(self, product_id: int):
        self.product_id = product_id
        super().__init__(
            message="The product has no price in the quote's lists nor its own: "
            "give it a sale price first",
            detail=f"product_id={product_id}",
        )
