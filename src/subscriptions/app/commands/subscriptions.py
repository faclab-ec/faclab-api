"""A tenant's subscription: created with the tenant (provisioning) and changed
by the platform (its CLI, S8.4). Both run in the tenant's context."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import structlog
from wireup import injectable

from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError
from src.subscriptions.app.repositories import PlanRepository, SubscriptionRepository
from src.subscriptions.domain.entities import Plan, Subscription, SubscriptionStatus
from src.subscriptions.domain.exceptions import DefaultPlanRequiredError

logger = structlog.get_logger(__name__)


def describe_subscription(subscription: Subscription, plan: Plan) -> dict[str, Any]:
    return {
        "plan_code": plan.code,
        "plan_name": plan.name,
        "status": subscription.status,
        "trial_ends_at": subscription.trial_ends_at,
        "status_changed_at": subscription.status_changed_at,
        "status_changed_by": subscription.status_changed_by,
    }


def _plan(plans: PlanRepository, code: str | None) -> Plan:
    if code is None:
        plan = plans.default()
        if plan is None:
            raise DefaultPlanRequiredError("There is no default plan")
        return plan
    plan = plans.first(code=code.strip().lower())
    if plan is None:
        raise NotFoundError(f"Plan '{code}' not found")
    return plan


@dataclass
class EnsureSubscriptionCommand(Command):
    # None: the default plan
    plan_code: str | None = None
    # A trial of that many days; None: active
    trial_days: int | None = None


@injectable(lifetime="scoped")
class EnsureSubscriptionCommandHandler(CommandHandler[EnsureSubscriptionCommand, dict]):
    """The context tenant's subscription, created when it has none. A tenant
    that already has one keeps it as it is (provisioning is idempotent)"""

    def __init__(self, plans: PlanRepository, subscriptions: SubscriptionRepository):
        self.plans = plans
        self.subscriptions = subscriptions

    def _handle(self, command: EnsureSubscriptionCommand) -> dict:
        if self.subscriptions.current() is not None:
            return {"subscription_created": False}
        plan = _plan(self.plans, command.plan_code)
        plan.ensure_assignable()
        now = datetime.now()
        subscription = Subscription(plan_id=plan.require_id())
        subscription.change_status(
            SubscriptionStatus.TRIAL
            if command.trial_days
            else SubscriptionStatus.ACTIVE,
            by="provisioning",
            now=now,
            trial_ends_at=(
                now + timedelta(days=command.trial_days) if command.trial_days else None
            ),
        )
        subscription = self.subscriptions.create(subscription)
        return {
            "subscription_created": True,
            **describe_subscription(subscription, plan),
        }


@dataclass
class ChangeSubscriptionCommand(Command):
    by: str
    plan_code: str | None = None
    status: SubscriptionStatus | None = None
    # With status trial: its days from now
    trial_days: int | None = None


@injectable(lifetime="scoped")
class ChangeSubscriptionCommandHandler(CommandHandler[ChangeSubscriptionCommand, dict]):
    """The platform changes the context tenant's plan or status. A tenant
    without a subscription gets one on the default plan first"""

    def __init__(self, plans: PlanRepository, subscriptions: SubscriptionRepository):
        self.plans = plans
        self.subscriptions = subscriptions

    def _handle(self, command: ChangeSubscriptionCommand) -> dict:
        now = datetime.now()
        subscription = self.subscriptions.lock_current()
        if subscription is None:
            default = _plan(self.plans, None)
            subscription = self.subscriptions.create(
                Subscription(plan_id=default.require_id())
            )
        before_plan = subscription.plan_id
        before_status = subscription.status
        if command.plan_code is not None:
            subscription.change_plan(
                _plan(self.plans, command.plan_code), by=command.by, now=now
            )
        if command.status is not None:
            subscription.change_status(
                command.status,
                by=command.by,
                now=now,
                trial_ends_at=(
                    now + timedelta(days=command.trial_days)
                    if command.trial_days
                    else None
                ),
            )
        subscription = self.subscriptions.update(subscription)
        plan = self.plans.get_by_id(subscription.plan_id)
        if plan is None:
            raise NotFoundError(f"Plan {subscription.plan_id} not found")
        logger.info(
            "subscription_changed",
            by=command.by,
            plan_before=before_plan,
            plan=subscription.plan_id,
            status_before=before_status.value,
            status=subscription.status.value,
        )
        return describe_subscription(subscription, plan)
