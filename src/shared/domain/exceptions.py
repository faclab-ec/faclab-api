class BaseError(Exception):
    error_code: str = "INTERNAL_ERROR"
    # The request transaction commits the changes flushed before this error
    # instead of rolling them back, e.g. a failed login attempt that must be
    # counted even though the request fails
    commit_transaction: bool = False

    def __init__(self, message: str, detail: str | None = None):
        self.message = message
        self.detail = detail
        super().__init__(message)

    def __str__(self):
        return self.message


class DomainError(BaseError):
    error_code = "DOMAIN_ERROR"


class ApplicationError(BaseError):
    error_code = "APPLICATION_ERROR"


class NotFoundError(ApplicationError):
    error_code = "NOT_FOUND"


class ValidationError(DomainError):
    error_code = "VALIDATION_ERROR"


class InvalidValueError(ValidationError, ValueError):
    """A value object or entity rejected a value. Still a ValueError for callers
    that expect one, but answered with its own message (422) instead of the
    generic text the API gives to unexpected ValueErrors."""


class ConflictError(DomainError):
    """The operation conflicts with data that already exists (HTTP 409)."""

    error_code = "CONFLICT"


class AlreadyExistsError(ConflictError):
    """A unique value is already taken. Subclasses use `<THING>_ALREADY_EXISTS`."""

    error_code = "ALREADY_EXISTS"


class IdempotencyKeyRequiredError(ValidationError):
    """A POST that creates a document or moves money came without its key"""

    error_code = "IDEMPOTENCY_KEY_REQUIRED"

    def __init__(self):
        super().__init__(
            "Send an Idempotency-Key header: a UUID generated once per operation "
            "and resent on every retry of it"
        )


class InvalidIdempotencyKeyError(ValidationError):
    error_code = "INVALID_IDEMPOTENCY_KEY"

    def __init__(self):
        super().__init__("The Idempotency-Key header must be a UUID")


class IdempotencyKeyReusedError(ValidationError):
    """The key already belongs to another request (another body or route)"""

    error_code = "IDEMPOTENCY_KEY_REUSED"

    def __init__(self):
        super().__init__(
            "This Idempotency-Key was already used for a different request"
        )


class IdempotencyInProgressError(ConflictError):
    """Another request with the key is still running"""

    error_code = "IDEMPOTENCY_IN_PROGRESS"

    def __init__(self):
        super().__init__(
            "A request with this Idempotency-Key is still in progress: retry later"
        )
