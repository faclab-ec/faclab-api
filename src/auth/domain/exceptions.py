from src.shared.domain.exceptions import (
    AlreadyExistsError,
    ApplicationError,
    ConflictError,
)


class InvalidCredentialsError(ApplicationError):
    error_code = "INVALID_CREDENTIALS"


class TokenExpiredError(ApplicationError):
    error_code = "TOKEN_EXPIRED"


class InvalidTokenError(ApplicationError):
    error_code = "INVALID_TOKEN"


class PermissionDeniedError(ApplicationError):
    error_code = "PERMISSION_DENIED"


class PasswordChangeRequiredError(ApplicationError):
    error_code = "PASSWORD_CHANGE_REQUIRED"


class UsernameAlreadyExistsError(AlreadyExistsError):
    error_code = "USERNAME_ALREADY_EXISTS"

    def __init__(self, message: str = "username already exists"):
        super().__init__(message)


class EmailAlreadyExistsError(AlreadyExistsError):
    error_code = "EMAIL_ALREADY_EXISTS"

    def __init__(self, message: str = "email already exists"):
        super().__init__(message)


class LastAdminError(ConflictError):
    """Deactivating or demoting this user would leave no active admin"""

    error_code = "LAST_ADMIN"

    def __init__(self, user_id: int):
        super().__init__(
            "the last active admin cannot be deactivated or change role",
            detail=f"user_id={user_id}",
        )
