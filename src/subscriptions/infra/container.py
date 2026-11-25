from wireup import injectable

from config import config
from src.subscriptions.app.commands.plans import (
    CreatePlanCommandHandler,
    UpdatePlanCommandHandler,
)
from src.subscriptions.app.commands.subscriptions import (
    ChangeSubscriptionCommandHandler,
    EnsureSubscriptionCommandHandler,
)
from src.subscriptions.app.commands.usage import CountDocumentCommandHandler
from src.subscriptions.app.integration_plan import SubscriptionIntegrationPlan
from src.subscriptions.app.plans import (
    SubscriptionPlanLimits,
    SubscriptionSettings,
    TenantPlan,
)
from src.subscriptions.app.queries.subscription import (
    GetSubscriptionQueryHandler,
    GetSubscriptionStatusQueryHandler,
)
from src.subscriptions.infra.mappers import PlanMapper, SubscriptionMapper
from src.subscriptions.infra.repositories import (
    SqlAlchemyDocumentUsageRepository,
    SqlAlchemyPlanRepository,
    SqlAlchemySubscriptionRepository,
)
from src.subscriptions.infra.usage import SqlAlchemyTenantUsage


@injectable(lifetime="singleton")
def subscription_settings() -> SubscriptionSettings:
    return SubscriptionSettings(enforcement_enabled=config.PLAN_ENFORCEMENT_ENABLED)


INJECTABLES = [
    subscription_settings,
    PlanMapper,
    SubscriptionMapper,
    SqlAlchemyPlanRepository,
    SqlAlchemySubscriptionRepository,
    SqlAlchemyDocumentUsageRepository,
    SqlAlchemyTenantUsage,
    TenantPlan,
    SubscriptionPlanLimits,
    SubscriptionIntegrationPlan,
    CreatePlanCommandHandler,
    UpdatePlanCommandHandler,
    EnsureSubscriptionCommandHandler,
    ChangeSubscriptionCommandHandler,
    CountDocumentCommandHandler,
    GetSubscriptionQueryHandler,
    GetSubscriptionStatusQueryHandler,
]
