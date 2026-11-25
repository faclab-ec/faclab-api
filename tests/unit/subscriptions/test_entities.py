from datetime import UTC, date, datetime, timedelta

import pytest

from src.shared.app.plans import PlanResource
from src.shared.domain.exceptions import InvalidValueError
from src.subscriptions.domain.entities import (
    Plan,
    Subscription,
    SubscriptionStatus,
    period_of,
    previous_periods,
)
from src.subscriptions.domain.exceptions import PlanInactiveError, TrialEndRequiredError

NOW = datetime(2026, 11, 24, 10, 0)


def test_a_plan_names_its_limit_of_each_resource():
    plan = Plan(code="Basico", name=" Básico ", max_branches=1, max_users=3)

    assert (plan.code, plan.name) == ("basico", "Básico")
    assert plan.limit_of(PlanResource.BRANCHES) == 1
    assert plan.limit_of(PlanResource.USERS) == 3
    assert plan.limit_of(PlanResource.TERMINALS) is None
    assert set(plan.limits()) == set(PlanResource)


@pytest.mark.parametrize(
    "values",
    [
        {"code": "B", "name": "x"},
        {"code": "con espacio", "name": "x"},
        {"code": "basico", "name": "  "},
        # Provisioning creates one branch, one terminal and the first admin
        {"code": "basico", "name": "x", "max_branches": 0},
        {"code": "basico", "name": "x", "max_terminals": 0},
        {"code": "basico", "name": "x", "max_users": 0},
        {"code": "basico", "name": "x", "max_webhook_endpoints": -1},
        {"code": "basico", "name": "x", "max_monthly_documents": -1},
    ],
)
def test_a_plan_rejects_invalid_values(values):
    with pytest.raises(InvalidValueError):
        Plan(**values)


def test_a_plan_may_leave_out_integrations_entirely():
    plan = Plan(
        code="basico", name="Básico", max_integration_clients=0, public_api=False
    )

    assert plan.limit_of(PlanResource.INTEGRATION_CLIENTS) == 0


@pytest.mark.parametrize(
    ("status", "trial_ends_at", "writes"),
    [
        (SubscriptionStatus.ACTIVE, None, True),
        (SubscriptionStatus.TRIAL, NOW + timedelta(days=1), True),
        (SubscriptionStatus.TRIAL, NOW - timedelta(seconds=1), False),
        (SubscriptionStatus.TRIAL, None, False),
        (SubscriptionStatus.SUSPENDED, None, False),
        (SubscriptionStatus.CANCELLED, None, False),
    ],
)
def test_only_an_active_subscription_or_a_running_trial_writes(
    status, trial_ends_at, writes
):
    subscription = Subscription(plan_id=1, status=status, trial_ends_at=trial_ends_at)

    assert subscription.allows_writes(NOW) is writes


def test_a_trial_needs_its_end():
    subscription = Subscription(plan_id=1)

    with pytest.raises(TrialEndRequiredError):
        subscription.change_status(SubscriptionStatus.TRIAL, by="ops", now=NOW)


def test_changing_the_status_records_who_and_when_and_drops_the_trial_end():
    subscription = Subscription(
        plan_id=1,
        status=SubscriptionStatus.TRIAL,
        trial_ends_at=NOW + timedelta(days=5),
    )

    subscription.change_status(SubscriptionStatus.SUSPENDED, by="ops", now=NOW)

    assert subscription.status is SubscriptionStatus.SUSPENDED
    assert subscription.trial_ends_at is None
    assert (subscription.status_changed_by, subscription.status_changed_at) == (
        "ops",
        NOW,
    )


def test_an_inactive_plan_is_not_given():
    subscription = Subscription(plan_id=1)
    plan = Plan(id=2, code="viejo", name="Viejo", is_active=False)

    with pytest.raises(PlanInactiveError):
        subscription.change_plan(plan, by="ops", now=NOW)
    assert subscription.plan_id == 1


def test_a_document_counts_in_its_month_in_ecuador():
    # 03:00 UTC on December 1st is still November 30th in Ecuador (UTC-5)
    assert period_of(datetime(2026, 12, 1, 3, 0, tzinfo=UTC)) == date(2026, 11, 1)
    assert period_of(datetime(2026, 12, 1, 5, 0, tzinfo=UTC)) == date(2026, 12, 1)
    # A naive moment is UTC
    assert period_of(datetime(2026, 12, 1, 4, 59)) == date(2026, 11, 1)


def test_the_previous_periods_cross_the_year():
    assert previous_periods(date(2026, 2, 1), 4) == [
        date(2025, 11, 1),
        date(2025, 12, 1),
        date(2026, 1, 1),
        date(2026, 2, 1),
    ]
