"""The limits of the tenant's plan (S8.4).

A command that adds a limited resource (a branch, a terminal, a user, an
integration client, a webhook endpoint) asks `PlanLimits.ensure_room` before
adding it, like it records its audit entry through `AuditTrail`: modules never
import `src/subscriptions`. A full plan answers 409 `PLAN_LIMIT_REACHED`.
"""

from abc import ABC, abstractmethod
from enum import StrEnum

from src.shared.domain.exceptions import ConflictError


class PlanResource(StrEnum):
    """What a plan limits. Each one is a `max_<value>` of the plan"""

    BRANCHES = "branches"
    TERMINALS = "terminals"
    USERS = "users"
    INTEGRATION_CLIENTS = "integration_clients"
    WEBHOOK_ENDPOINTS = "webhook_endpoints"


class PlanLimitReachedError(ConflictError):
    error_code = "PLAN_LIMIT_REACHED"

    def __init__(self, resource: PlanResource, limit: int):
        super().__init__(
            f"The tenant's plan allows {limit} {resource.value.replace('_', ' ')}",
            extra={"resource": resource.value, "limit": limit},
        )


class PlanLimits(ABC):
    @abstractmethod
    def ensure_room(self, resource: PlanResource) -> None:
        """Raises `PlanLimitReachedError` when the context tenant's plan has no
        room for one more `resource`. Concurrent checks of a tenant take turns
        until their transactions end, so two of them never take the last seat.
        Without a tenant context (a platform action) it lets everything through.
        """
