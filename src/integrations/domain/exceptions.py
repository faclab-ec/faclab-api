from src.shared.domain.exceptions import ConflictError, ValidationError


class IntegrationClientRevokedError(ConflictError):
    error_code = "INTEGRATION_CLIENT_REVOKED"

    def __init__(self):
        super().__init__("The integration client is revoked")


class IntegrationSecretLimitReachedError(ConflictError):
    error_code = "INTEGRATION_SECRET_LIMIT_REACHED"

    def __init__(self, limit: int):
        super().__init__(
            f"The client already has {limit} active secrets: revoke one, or make "
            "the current ones expire, before adding another"
        )


class IntegrationSecretRevokedError(ConflictError):
    error_code = "INTEGRATION_SECRET_REVOKED"

    def __init__(self):
        super().__init__("The secret is already revoked")


class ScopeNotInPlanError(ConflictError):
    """A scope the tenant's plan doesn't include (S8.4 sets the plans)"""

    error_code = "SCOPE_NOT_IN_PLAN"

    def __init__(self, scopes: list[str]):
        super().__init__(f"The tenant's plan doesn't include the scopes {scopes}")


class IntegrationBranchNotFoundError(ValidationError):
    """A branch of the client that isn't the tenant's"""

    error_code = "REFERENCE_NOT_FOUND"

    def __init__(self, branch_ids: list[int]):
        super().__init__(f"Branches not found: {branch_ids}")
