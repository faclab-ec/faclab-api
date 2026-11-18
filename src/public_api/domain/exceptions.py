"""Errors of the public API `/api/v1` (S6.3). Their codes are part of its
public error catalog (`src/public_api/infra/errors.py`)."""

from src.auth.domain.exceptions import PermissionDeniedError
from src.shared.domain.exceptions import (
    AlreadyExistsError,
    ApplicationError,
    BaseError,
    ConflictError,
    ValidationError,
)


class PublicApiDisabledError(BaseError):
    """PUBLIC_API_ENABLED=false: the rollback switch (503)"""

    error_code = "PUBLIC_API_DISABLED"

    def __init__(self):
        super().__init__("The public API is disabled")


class RateLimitedError(BaseError):
    """The client or its tenant went over its rate limit (429)"""

    error_code = "RATE_LIMITED"

    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Too many requests: retry in {retry_after} seconds")


class InvalidSortError(ValidationError):
    """`sort` names a field the resource can't be ordered by"""

    def __init__(self, value: str, allowed: list[str]):
        super().__init__(
            f"Can't sort by {value!r}",
            detail=f"Allowed: {', '.join(allowed)}, each optionally with a leading -",
            extra={"field": "sort"},
        )


class BranchIdRequiredError(ValidationError):
    """A listing by branch of a client that may enter several of them"""

    error_code = "BRANCH_REQUIRED"

    def __init__(self):
        super().__init__(
            "Send branchId: this client may operate in more than one branch",
            extra={"field": "branchId"},
        )


class PaymentMethodNotAllowedError(ValidationError):
    """A sale of the public API is paid online: no cash drawer, no credit"""

    error_code = "PAYMENT_METHOD_NOT_ALLOWED"

    def __init__(self, method: str, allowed: list[str]):
        super().__init__(
            f"A sale of the public API can't be paid with {method}",
            detail=f"Allowed: {', '.join(allowed)}",
        )


class EmissionPointInactiveError(ConflictError):
    error_code = "EMISSION_POINT_INACTIVE"

    def __init__(self, emission_point_id: int):
        super().__init__(f"Emission point {emission_point_id} is inactive")


class LocationInactiveError(ConflictError):
    error_code = "LOCATION_INACTIVE"

    def __init__(self, location_id: int):
        super().__init__(f"Location {location_id} is inactive")


class CustomerInactiveError(ConflictError):
    error_code = "CUSTOMER_INACTIVE"

    def __init__(self, customer_id: int):
        super().__init__(f"Customer {customer_id} is inactive")


class SaleNotFromClientError(PermissionDeniedError):
    """An integration client only changes the sales it created"""

    def __init__(self, sale_id: int):
        super().__init__(f"Sale {sale_id} was not created by this integration client")


class CustomerAlreadyExistsError(AlreadyExistsError):
    """A customer with that identification exists: its id goes with the error"""

    error_code = "CUSTOMER_ALREADY_EXISTS"

    def __init__(self, existing_id: int):
        super().__init__(
            "A customer with this identification already exists",
            extra={"existing_id": existing_id},
        )


class ReferenceNotFoundError(ApplicationError):
    """A record the body names doesn't exist (422, like a foreign key's)"""

    error_code = "REFERENCE_NOT_FOUND"

    def __init__(self, message: str, field: str):
        super().__init__(message, extra={"field": field})
