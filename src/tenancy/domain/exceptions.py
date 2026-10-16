from src.shared.domain.exceptions import (
    AlreadyExistsError,
    NotFoundError,
    ValidationError,
)


class TenantNotFoundError(NotFoundError):
    def __init__(self, message: str = "tenant not found"):
        super().__init__(message)


class TenantRucAlreadyExistsError(AlreadyExistsError):
    error_code = "TENANT_RUC_ALREADY_EXISTS"

    def __init__(self, message: str = "a tenant with this RUC already exists"):
        super().__init__(message)


class MembershipAlreadyExistsError(AlreadyExistsError):
    error_code = "MEMBERSHIP_ALREADY_EXISTS"

    def __init__(self, message: str = "the user already belongs to this tenant"):
        super().__init__(message)


class AdminPasswordRequiredError(ValidationError):
    def __init__(
        self, message: str = "the admin user doesn't exist yet: give it a password"
    ):
        super().__init__(message)
