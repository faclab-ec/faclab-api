from src.shared.domain.exceptions import ConflictError, NotFoundError


class PlatformOperatorNotFoundError(NotFoundError):
    def __init__(self, message: str = "platform operator not found"):
        super().__init__(message)


class TenantAlreadySuspendedError(ConflictError):
    error_code = "TENANT_ALREADY_SUSPENDED"

    def __init__(self, message: str = "the tenant is already suspended"):
        super().__init__(message)


class TenantNotSuspendedError(ConflictError):
    error_code = "TENANT_NOT_SUSPENDED"

    def __init__(self, message: str = "the tenant is not suspended"):
        super().__init__(message)
