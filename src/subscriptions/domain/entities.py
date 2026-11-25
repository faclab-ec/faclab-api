"""Plans, subscriptions and the monthly usage of electronic documents (S8.4).

A plan limits what a tenant may add (`None`: no limit). Each tenant has one
subscription to a plan with a status: in `trial` until its end date and
`active` it works in full; `suspended`, `cancelled` and a trial past its end
leave it read-only (it reads, it can't create sales or change data), while the
invoicing of what it already sold goes on. The tenant's own `status`
(`tenants.status`) is another thing: a suspended tenant can't even log in.

The plans have no prices: decision D-5 is still open (GAP_ANALYSIS §5.3).
"""

import re
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime, timedelta, timezone
from enum import StrEnum

from src.shared.app.plans import PlanResource
from src.shared.domain.entities import Entity
from src.shared.domain.exceptions import InvalidValueError
from src.subscriptions.domain.exceptions import PlanInactiveError, TrialEndRequiredError

# Continental Ecuador is UTC-5 all year (no daylight saving time): the month a
# document counts in. A fixed offset needs no time zone database in the image
ECUADOR = timezone(timedelta(hours=-5), "ECT")

PLAN_CODE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
# Provisioning creates the main branch, its terminal and the first admin, so a
# plan allows at least one of each
REQUIRED_RESOURCES = frozenset(
    {PlanResource.BRANCHES, PlanResource.TERMINALS, PlanResource.USERS}
)


def period_of(moment: datetime) -> date:
    """The first day of the month of `moment` in Ecuador. A naive moment is UTC"""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(ECUADOR).date().replace(day=1)


def previous_periods(period: date, months: int) -> list[date]:
    """`months` periods ending at `period`, oldest first"""
    periods = [period]
    while len(periods) < months:
        first = periods[0]
        periods.insert(0, (first - timedelta(days=1)).replace(day=1))
    return periods


class SubscriptionStatus(StrEnum):
    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


@dataclass
class Plan(Entity):
    code: str
    name: str
    max_branches: int | None = None
    max_terminals: int | None = None
    max_users: int | None = None
    max_integration_clients: int | None = None
    max_webhook_endpoints: int | None = None
    # A soft limit: the documents of sales already made are always issued (S8.4)
    max_monthly_documents: int | None = None
    public_api: bool = True
    is_default: bool = False
    is_active: bool = True
    id: int | None = None

    def __post_init__(self):
        self.code = self.code.strip().lower()
        if not PLAN_CODE.match(self.code):
            raise InvalidValueError(
                f"plan code '{self.code}': 2 to 40 lowercase letters, digits or dashes"
            )
        self.name = self.name.strip()
        if not self.name:
            raise InvalidValueError("the plan's name is required")
        for name, value in self.limits().items():
            minimum = 1 if name in REQUIRED_RESOURCES else 0
            if value is not None and value < minimum:
                raise InvalidValueError(f"max_{name} must be {minimum} or more")
        if self.max_monthly_documents is not None and self.max_monthly_documents < 0:
            raise InvalidValueError("max_monthly_documents must be 0 or more")

    def limit_of(self, resource: PlanResource) -> int | None:
        return getattr(self, f"max_{resource.value}")

    def limits(self) -> dict[PlanResource, int | None]:
        return {resource: self.limit_of(resource) for resource in PlanResource}

    def ensure_assignable(self) -> None:
        if not self.is_active:
            raise PlanInactiveError(self.code)


PLAN_FIELDS = tuple(field.name for field in fields(Plan) if field.name != "id")


@dataclass
class Subscription(Entity):
    """The plan a tenant has and the status of its subscription"""

    plan_id: int
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    trial_ends_at: datetime | None = None
    status_changed_at: datetime | None = None
    # Who changed it last: the platform operator (`--by` of the CLI)
    status_changed_by: str | None = None
    id: int | None = None

    def allows_writes(self, now: datetime) -> bool:
        if self.status is SubscriptionStatus.ACTIVE:
            return True
        if self.status is SubscriptionStatus.TRIAL:
            return self.trial_ends_at is not None and now < self.trial_ends_at
        return False

    def change_status(
        self,
        status: SubscriptionStatus,
        *,
        by: str,
        now: datetime,
        trial_ends_at: datetime | None = None,
    ) -> None:
        if status is SubscriptionStatus.TRIAL and trial_ends_at is None:
            raise TrialEndRequiredError()
        self.status = status
        self.trial_ends_at = (
            trial_ends_at if status is SubscriptionStatus.TRIAL else None
        )
        self.status_changed_at = now
        self.status_changed_by = by

    def change_plan(self, plan: Plan, *, by: str, now: datetime) -> None:
        plan.ensure_assignable()
        self.plan_id = plan.require_id()
        self.status_changed_at = now
        self.status_changed_by = by


@dataclass
class DocumentUsage:
    """The electronic documents the SRI authorized to a tenant in a month"""

    period: date
    invoices: int = 0
    credit_notes: int = 0

    @property
    def total(self) -> int:
        return self.invoices + self.credit_notes
