from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from wireup import injectable

from src.shared.app.plans import PlanResource
from src.shared.app.queries import Query, QueryHandler
from src.subscriptions.app.plans import SubscriptionSettings, TenantPlan
from src.subscriptions.app.repositories import DocumentUsageRepository, TenantUsage
from src.subscriptions.domain.entities import (
    Plan,
    Subscription,
    SubscriptionStatus,
    period_of,
    previous_periods,
)

# The months the usage screen shows, the current one last
USAGE_MONTHS = 6


def _status(subscription: Subscription | None) -> SubscriptionStatus:
    return subscription.status if subscription else SubscriptionStatus.ACTIVE


def _read_only(
    subscription: Subscription | None, settings: SubscriptionSettings
) -> bool:
    """Read-only only while the plans are enforced (PLAN_ENFORCEMENT_ENABLED)"""
    return (
        settings.enforcement_enabled
        and subscription is not None
        and not subscription.allows_writes(datetime.now())
    )


def _plan(plan: Plan | None) -> dict[str, Any] | None:
    if plan is None:
        return None
    return {
        "code": plan.code,
        "name": plan.name,
        "public_api": plan.public_api,
        "max_monthly_documents": plan.max_monthly_documents,
        **{
            f"max_{resource.value}": plan.limit_of(resource)
            for resource in PlanResource
        },
    }


@dataclass
class GetSubscriptionQuery(Query):
    pass


@injectable(lifetime="scoped")
class GetSubscriptionQueryHandler(QueryHandler[GetSubscriptionQuery, dict]):
    """The context tenant's plan, the status of its subscription, what it uses
    of each limit and its documents of the last months"""

    def __init__(
        self,
        plan: TenantPlan,
        resources: TenantUsage,
        documents: DocumentUsageRepository,
        settings: SubscriptionSettings,
    ):
        self.plan = plan
        self.resources = resources
        self.documents = documents
        self.settings = settings

    def _handle(self, query: GetSubscriptionQuery) -> dict:
        subscription, plan = self.plan.current()
        months = self.documents.months(
            previous_periods(period_of(datetime.now(UTC)), USAGE_MONTHS)
        )
        return {
            "plan": _plan(plan),
            "status": _status(subscription),
            "trial_ends_at": subscription.trial_ends_at if subscription else None,
            "read_only": _read_only(subscription, self.settings),
            "resources": [
                {
                    "resource": resource,
                    "used": self.resources.count(resource),
                    "limit": plan.limit_of(resource) if plan else None,
                }
                for resource in PlanResource
            ],
            "documents": {
                "limit": plan.max_monthly_documents if plan else None,
                "months": [
                    {
                        "period": month.period,
                        "invoices": month.invoices,
                        "credit_notes": month.credit_notes,
                        "total": month.total,
                    }
                    for month in months
                ],
            },
        }


@dataclass
class GetSubscriptionStatusQuery(Query):
    pass


@injectable(lifetime="scoped")
class GetSubscriptionStatusQueryHandler(QueryHandler[GetSubscriptionStatusQuery, dict]):
    """What every user of the tenant sees of it (`/api/auth/me`): whether it can
    write, when its trial ends and whether this month's documents reached the
    plan's limit"""

    def __init__(
        self,
        plan: TenantPlan,
        documents: DocumentUsageRepository,
        settings: SubscriptionSettings,
    ):
        self.plan = plan
        self.documents = documents
        self.settings = settings

    def _handle(self, query: GetSubscriptionStatusQuery) -> dict:
        subscription, plan = self.plan.current()
        limit = plan.max_monthly_documents if plan else None
        reached = False
        if limit is not None:
            (month,) = self.documents.months([period_of(datetime.now(UTC))])
            reached = month.total >= limit
        return {
            "plan_name": plan.name if plan else None,
            "status": _status(subscription),
            "trial_ends_at": subscription.trial_ends_at if subscription else None,
            "read_only": _read_only(subscription, self.settings),
            "documents_limit_reached": reached,
        }
