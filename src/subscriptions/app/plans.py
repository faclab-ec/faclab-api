"""The context tenant's plan and how it applies (S8.4)."""

from dataclasses import dataclass

from wireup import injectable

from src.shared.app.plans import PlanLimitReachedError, PlanLimits, PlanResource
from src.shared.domain.tenant import current_tenant
from src.subscriptions.app.repositories import (
    PlanRepository,
    SubscriptionRepository,
    TenantUsage,
)
from src.subscriptions.domain.entities import Plan, Subscription


@dataclass(frozen=True)
class SubscriptionSettings:
    # PLAN_ENFORCEMENT_ENABLED: false applies no limit nor read-only mode (the
    # rollback switch); the usage is still measured and shown
    enforcement_enabled: bool = True


@injectable(lifetime="scoped")
class TenantPlan:
    """The subscription and plan of the context tenant. A tenant without a
    subscription row has the default plan, active; without a default plan
    (a database never migrated) it has none, which limits nothing."""

    def __init__(self, plans: PlanRepository, subscriptions: SubscriptionRepository):
        self.plans = plans
        self.subscriptions = subscriptions

    def current(self, lock: bool = False) -> tuple[Subscription | None, Plan | None]:
        subscription = (
            self.subscriptions.lock_current() if lock else self.subscriptions.current()
        )
        if subscription is None:
            return None, self.plans.default()
        return subscription, self.plans.get_by_id(subscription.plan_id)


@injectable(lifetime="scoped", as_type=PlanLimits)
class SubscriptionPlanLimits(PlanLimits):
    def __init__(
        self,
        plan: TenantPlan,
        usage: TenantUsage,
        settings: SubscriptionSettings,
    ):
        self.plan = plan
        self.usage = usage
        self.settings = settings

    def ensure_room(self, resource: PlanResource) -> None:
        if not self.settings.enforcement_enabled or current_tenant() is None:
            return
        # The subscription's row is the tenant's turn: a concurrent check
        # waits here until this transaction ends, then counts what it added
        _, plan = self.plan.current(lock=True)
        limit = plan.limit_of(resource) if plan is not None else None
        if limit is None:
            return
        if self.usage.count(resource) >= limit:
            raise PlanLimitReachedError(resource, limit)
