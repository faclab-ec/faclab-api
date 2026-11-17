"""What the tenant's plan lets its integrations do (S6.2).

An extension point for S8.4 (plans and limits): today every plan includes
every scope. The scopes of a client must be in the plan when it is created or
changed, and a token only gets the ones the plan still includes.
"""

from abc import ABC, abstractmethod

from wireup import injectable

from src.auth.domain.scopes import Scope


class IntegrationPlan(ABC):
    @abstractmethod
    def allowed_scopes(self) -> frozenset[Scope]:
        """The scopes the context tenant's plan allows"""


@injectable(lifetime="scoped", as_type=IntegrationPlan)
class UnlimitedIntegrationPlan(IntegrationPlan):
    def allowed_scopes(self) -> frozenset[Scope]:
        return frozenset(Scope)
