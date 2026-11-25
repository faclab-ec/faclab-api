from src.shared.domain.exceptions import (
    AlreadyExistsError,
    ConflictError,
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


class TenantOffboardedError(ConflictError):
    """Its data was anonymized (S8.7): it can't be activated or taken back"""

    error_code = "TENANT_OFFBOARDED"

    def __init__(self, message: str = "the tenant was offboarded"):
        super().__init__(message)


class OffboardingAlreadyStartedError(ConflictError):
    error_code = "OFFBOARDING_ALREADY_STARTED"

    def __init__(self, message: str = "the tenant's offboarding already started"):
        super().__init__(message)


class OffboardingNotStartedError(ConflictError):
    error_code = "OFFBOARDING_NOT_STARTED"

    def __init__(self, message: str = "the tenant's offboarding didn't start"):
        super().__init__(message)
