from wireup import injectable

from src.auth.domain.scopes import Scope
from src.integrations.app.plan import IntegrationPlan
from src.subscriptions.app.plans import SubscriptionSettings, TenantPlan


@injectable(lifetime="scoped", as_type=IntegrationPlan)
class SubscriptionIntegrationPlan(IntegrationPlan):
    """Every scope when the tenant's plan includes the public API, none when it
    doesn't (S8.4): a client can't be given one, and its new tokens get none"""

    def __init__(self, plan: TenantPlan, settings: SubscriptionSettings):
        self.plan = plan
        self.settings = settings

    def allowed_scopes(self) -> frozenset[Scope]:
        if not self.settings.enforcement_enabled:
            return frozenset(Scope)
        _, plan = self.plan.current()
        if plan is None or plan.public_api:
            return frozenset(Scope)
        return frozenset()
