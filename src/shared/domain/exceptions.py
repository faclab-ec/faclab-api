class BaseError(Exception):
    error_code: str = "INTERNAL_ERROR"

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


class ConflictError(DomainError):
    """The operation conflicts with data that already exists (HTTP 409)."""

    error_code = "CONFLICT"


class AlreadyExistsError(ConflictError):
    """A unique value is already taken. Subclasses use `<THING>_ALREADY_EXISTS`."""

    error_code = "ALREADY_EXISTS"
