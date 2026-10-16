from src.shared.domain.exceptions import (
    AlreadyExistsError,
    ApplicationError,
    ConflictError,
)


class InvalidCredentialsError(ApplicationError):
    error_code = "INVALID_CREDENTIALS"


class TokenExpiredError(ApplicationError):
    error_code = "TOKEN_EXPIRED"


class LoginFailedError(InvalidCredentialsError):
    """Wrong username or password. The failed attempt it recorded is committed
    even though the request fails, so it counts towards the lockout."""

    commit_transaction = True

    def __init__(self, message: str = "invalid username or password"):
        super().__init__(message)


class LoginLockedError(ApplicationError):
    error_code = "LOGIN_LOCKED"

    def __init__(
        self,
        message: str = "too many failed login attempts; try again later",
    ):
        super().__init__(message)


class InvalidTokenError(ApplicationError):
    error_code = "INVALID_TOKEN"


class TokenReusedError(ApplicationError):
    """A refresh token that was already rotated came back: it may be stolen, so
    the session is revoked. The revocation is committed with the error."""

    error_code = "TOKEN_REUSED"
    commit_transaction = True

    def __init__(self, message: str = "refresh token already used; log in again"):
        super().__init__(message)


class PermissionDeniedError(ApplicationError):
    error_code = "PERMISSION_DENIED"


class PasswordChangeRequiredError(ApplicationError):
    error_code = "PASSWORD_CHANGE_REQUIRED"


class TenantRequiredError(ApplicationError):
    """An access token without a tenant (`tid`): issued before tenants existed
    or by something else. The client has to log in again."""

    error_code = "TENANT_REQUIRED"

    def __init__(self, message: str = "the token has no tenant; log in again"):
        super().__init__(message)


class NoActiveTenantError(ApplicationError):
    """Right credentials, but no active membership in an active tenant"""

    error_code = "NO_ACTIVE_TENANT"

    def __init__(self, message: str = "the user has no active tenant"):
        super().__init__(message)


class TenantAccessDeniedError(ApplicationError):
    error_code = "TENANT_ACCESS_DENIED"

    def __init__(self, message: str = "the user has no access to this tenant"):
        super().__init__(message)


class UsernameAlreadyExistsError(AlreadyExistsError):
    error_code = "USERNAME_ALREADY_EXISTS"

    def __init__(self, message: str = "username already exists"):
        super().__init__(message)


class EmailAlreadyExistsError(AlreadyExistsError):
    error_code = "EMAIL_ALREADY_EXISTS"

    def __init__(self, message: str = "email already exists"):
        super().__init__(message)


class LastAdminError(ConflictError):
    """Deactivating or demoting this user would leave the tenant without an
    active admin"""

    error_code = "LAST_ADMIN"

    def __init__(self, user_id: int):
        super().__init__(
            "the last active admin of the tenant cannot be deactivated or change role",
            detail=f"user_id={user_id}",
        )


class UserInOtherTenantsError(ConflictError):
    """The password and the name are the same in every tenant, so the admin of
    one tenant can't change them for a user who also works in another."""

    error_code = "USER_IN_OTHER_TENANTS"

    def __init__(self, user_id: int):
        super().__init__(
            "the user also belongs to another tenant; their password and name "
            "can't be changed from this one",
            detail=f"user_id={user_id}",
        )
