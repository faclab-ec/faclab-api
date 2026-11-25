"""What the tenant's plan lets its integrations do (S6.2).

The scopes of a client must be in the plan when it is created or changed, and
a token only gets the ones the plan still includes. The subscriptions module
implements it (S8.4: every scope with the public API in the plan, none
without it); `UnlimitedIntegrationPlan` is for the tests.
"""

from abc import ABC, abstractmethod

from src.auth.domain.scopes import Scope


class IntegrationPlan(ABC):
    @abstractmethod
    def allowed_scopes(self) -> frozenset[Scope]:
        """The scopes the context tenant's plan allows"""


class UnlimitedIntegrationPlan(IntegrationPlan):
    def allowed_scopes(self) -> frozenset[Scope]:
        return frozenset(Scope)
