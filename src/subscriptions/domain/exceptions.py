from src.shared.domain.exceptions import (
    AlreadyExistsError,
    ConflictError,
    DomainError,
    ValidationError,
)


class PlanCodeAlreadyExistsError(AlreadyExistsError):
    error_code = "PLAN_CODE_ALREADY_EXISTS"


class PlanInactiveError(ConflictError):
    """An inactive plan is no longer given; the subscriptions on it keep it"""

    error_code = "PLAN_INACTIVE"

    def __init__(self, code: str):
        super().__init__(f"Plan '{code}' is inactive")


class DefaultPlanRequiredError(ConflictError):
    """There is always one active default plan: new tenants get it"""

    error_code = "DEFAULT_PLAN_REQUIRED"


class TrialEndRequiredError(ValidationError):
    error_code = "TRIAL_END_REQUIRED"

    def __init__(self):
        super().__init__("A trial needs its end date")


class SubscriptionReadOnlyError(DomainError):
    """The subscription is suspended or cancelled, or its trial ended: the
    tenant only reads (403)"""

    error_code = "SUBSCRIPTION_READ_ONLY"

    def __init__(self):
        super().__init__(
            "The company's subscription is not active: it can read but not "
            "create or change data"
        )
