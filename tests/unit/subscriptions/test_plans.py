"""Plans, subscriptions and the monthly documents over SQLite: the commands,
queries and repositories of the subscriptions module (S8.4)."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from src.auth.domain.scopes import Scope
from src.shared.app.plans import PlanLimitReachedError, PlanResource
from src.shared.domain.exceptions import InvalidValueError, NotFoundError
from src.shared.domain.tenant import TenantContext, TenantSource, use_tenant
from src.subscriptions.app.commands.plans import (
    CreatePlanCommand,
    CreatePlanCommandHandler,
    UpdatePlanCommand,
    UpdatePlanCommandHandler,
)
from src.subscriptions.app.commands.subscriptions import (
    ChangeSubscriptionCommand,
    ChangeSubscriptionCommandHandler,
    EnsureSubscriptionCommand,
    EnsureSubscriptionCommandHandler,
)
from src.subscriptions.app.commands.usage import (
    CountDocumentCommand,
    CountDocumentCommandHandler,
    DocumentKind,
)
from src.subscriptions.app.integration_plan import SubscriptionIntegrationPlan
from src.subscriptions.app.plans import (
    SubscriptionPlanLimits,
    SubscriptionSettings,
    TenantPlan,
)
from src.subscriptions.app.queries.subscription import (
    GetSubscriptionQuery,
    GetSubscriptionQueryHandler,
    GetSubscriptionStatusQuery,
    GetSubscriptionStatusQueryHandler,
)
from src.subscriptions.app.repositories import TenantUsage
from src.subscriptions.domain.entities import SubscriptionStatus
from src.subscriptions.domain.exceptions import (
    DefaultPlanRequiredError,
    PlanCodeAlreadyExistsError,
    PlanInactiveError,
)
from src.subscriptions.infra.mappers import PlanMapper, SubscriptionMapper
from src.subscriptions.infra.models import (
    DocumentUsageModel,
    PlanModel,
    SubscriptionModel,
)
from src.subscriptions.infra.repositories import (
    SqlAlchemyDocumentUsageRepository,
    SqlAlchemyPlanRepository,
    SqlAlchemySubscriptionRepository,
)
from src.tenancy.infra.models import TenantModel
from tests.sqlite import sqlite_session

OTHER_TENANT = TenantContext(
    UUID("00000000-0000-4000-8000-0000000000b2"), TenantSource.TASK
)


class CountedUsage(TenantUsage):
    def __init__(self, **used: int):
        self.used = {PlanResource(name): value for name, value in used.items()}

    def count(self, resource: PlanResource) -> int:
        return self.used.get(resource, 0)


@pytest.fixture
def session(in_tenant) -> Iterator[Session]:
    session = sqlite_session([PlanModel, SubscriptionModel, DocumentUsageModel])
    session.add(
        TenantModel(id=OTHER_TENANT.tenant_id, ruc="0999999999001", legal_name="Otra")
    )
    session.flush()
    yield session
    session.close()


def _plans(session: Session) -> SqlAlchemyPlanRepository:
    return SqlAlchemyPlanRepository(session, PlanMapper())


def _subscriptions(session: Session) -> SqlAlchemySubscriptionRepository:
    return SqlAlchemySubscriptionRepository(session, SubscriptionMapper())


def _tenant_plan(session: Session) -> TenantPlan:
    return TenantPlan(_plans(session), _subscriptions(session))


def _plan(session: Session, code: str, **values) -> dict:
    return CreatePlanCommandHandler(_plans(session)).handle(
        CreatePlanCommand(code=code, name=code.title(), **values)
    )


def _subscribe(session: Session, plan_code: str | None = None, **values) -> dict:
    return EnsureSubscriptionCommandHandler(
        _plans(session), _subscriptions(session)
    ).handle(EnsureSubscriptionCommand(plan_code=plan_code, **values))


def _change(session: Session, **values) -> dict:
    return ChangeSubscriptionCommandHandler(
        _plans(session), _subscriptions(session)
    ).handle(ChangeSubscriptionCommand(by="ops", **values))


def _limits(session: Session, enforced: bool = True, **used: int):
    return SubscriptionPlanLimits(
        _tenant_plan(session), CountedUsage(**used), SubscriptionSettings(enforced)
    )


# Plans


def test_there_is_one_default_plan(session):
    _plan(session, "ilimitado", is_default=True)
    _plan(session, "basico", limits={"max_branches": 1}, is_default=True)

    default = _plans(session).default()

    assert default is not None and default.code == "basico"
    previous = _plans(session).first(code="ilimitado")
    assert previous is not None and previous.is_default is False


def test_a_plan_code_is_unique(session):
    _plan(session, "basico")

    with pytest.raises(PlanCodeAlreadyExistsError):
        _plan(session, "basico")


def test_a_plan_takes_only_its_limits(session):
    with pytest.raises(InvalidValueError):
        _plan(session, "basico", limits={"max_warehouses": 1})


def test_updating_a_plan_changes_only_what_is_given(session):
    _plan(session, "basico", limits={"max_branches": 1, "max_users": 3})

    result = UpdatePlanCommandHandler(_plans(session)).handle(
        UpdatePlanCommand(code="basico", changes={"max_branches": None, "name": "B"})
    )

    assert (result["name"], result["max_branches"], result["max_users"]) == (
        "B",
        None,
        3,
    )


@pytest.mark.parametrize("changes", [{"is_active": False}, {"is_default": False}])
def test_the_default_plan_stays_active_and_default(session, changes):
    _plan(session, "ilimitado", is_default=True)

    with pytest.raises(DefaultPlanRequiredError):
        UpdatePlanCommandHandler(_plans(session)).handle(
            UpdatePlanCommand(code="ilimitado", changes=changes)
        )


def test_the_code_of_a_plan_never_changes(session):
    _plan(session, "basico")

    with pytest.raises(InvalidValueError):
        UpdatePlanCommandHandler(_plans(session)).handle(
            UpdatePlanCommand(code="basico", changes={"code": "otro"})
        )


# Subscriptions


def test_a_new_tenant_gets_the_default_plan_active(session):
    _plan(session, "ilimitado", is_default=True)

    result = _subscribe(session)

    assert result["subscription_created"] is True
    assert (result["plan_code"], result["status"]) == (
        "ilimitado",
        SubscriptionStatus.ACTIVE,
    )


def test_a_trial_ends_after_its_days(session):
    _plan(session, "basico")

    result = _subscribe(session, "basico", trial_days=30)

    assert result["status"] is SubscriptionStatus.TRIAL
    assert result["trial_ends_at"] > datetime.now() + timedelta(days=29)


def test_provisioning_again_keeps_the_subscription(session):
    _plan(session, "ilimitado", is_default=True)
    _plan(session, "basico")
    _subscribe(session, "basico")

    assert _subscribe(session) == {"subscription_created": False}
    _, plan = _tenant_plan(session).current()
    assert plan is not None and plan.code == "basico"


def test_without_a_default_plan_a_tenant_cant_be_subscribed(session):
    with pytest.raises(DefaultPlanRequiredError):
        _subscribe(session)


def test_the_platform_changes_the_plan_and_the_status(session):
    _plan(session, "ilimitado", is_default=True)
    _plan(session, "basico")
    _subscribe(session)

    result = _change(session, plan_code="basico", status=SubscriptionStatus.SUSPENDED)

    assert (result["plan_code"], result["status"]) == (
        "basico",
        SubscriptionStatus.SUSPENDED,
    )
    assert result["status_changed_by"] == "ops"


def test_a_tenant_without_a_subscription_gets_one_when_the_platform_changes_it(
    session,
):
    _plan(session, "ilimitado", is_default=True)

    result = _change(session, status=SubscriptionStatus.CANCELLED)

    assert (result["plan_code"], result["status"]) == (
        "ilimitado",
        SubscriptionStatus.CANCELLED,
    )


def test_an_inactive_plan_is_not_given(session):
    _plan(session, "ilimitado", is_default=True)
    _plan(session, "viejo")
    UpdatePlanCommandHandler(_plans(session)).handle(
        UpdatePlanCommand(code="viejo", changes={"is_active": False})
    )

    with pytest.raises(PlanInactiveError):
        _change(session, plan_code="viejo")


def test_an_unknown_plan_is_not_found(session):
    _plan(session, "ilimitado", is_default=True)

    with pytest.raises(NotFoundError):
        _change(session, plan_code="no-existe")


def test_the_subscription_is_the_context_tenants(session):
    _plan(session, "ilimitado", is_default=True)
    _plan(session, "basico")
    with use_tenant(OTHER_TENANT):
        _subscribe(session, "basico")

    subscription, plan = _tenant_plan(session).current()

    assert subscription is None
    assert plan is not None and plan.code == "ilimitado"


# Limits


def test_a_full_plan_refuses_one_more(session):
    _plan(session, "basico", limits={"max_branches": 2})
    _subscribe(session, "basico")

    _limits(session, branches=1).ensure_room(PlanResource.BRANCHES)
    with pytest.raises(PlanLimitReachedError) as error:
        _limits(session, branches=2).ensure_room(PlanResource.BRANCHES)

    assert error.value.error_code == "PLAN_LIMIT_REACHED"
    assert error.value.extra == {"resource": "branches", "limit": 2}


def test_without_a_limit_nothing_is_refused(session):
    _plan(session, "basico", limits={"max_branches": 1})
    _subscribe(session, "basico")

    _limits(session, terminals=500).ensure_room(PlanResource.TERMINALS)


def test_a_tenant_without_a_subscription_has_the_default_plans_limits(session):
    _plan(session, "ilimitado", limits={"max_users": 2}, is_default=True)

    with pytest.raises(PlanLimitReachedError):
        _limits(session, users=2).ensure_room(PlanResource.USERS)


def test_without_any_plan_nothing_is_refused(session):
    _limits(session, users=99).ensure_room(PlanResource.USERS)


def test_the_rollback_switch_refuses_nothing(session):
    _plan(session, "basico", limits={"max_branches": 1})
    _subscribe(session, "basico")

    _limits(session, enforced=False, branches=5).ensure_room(PlanResource.BRANCHES)


def test_a_platform_action_outside_every_tenant_is_not_limited(session):
    _plan(session, "ilimitado", limits={"max_users": 1}, is_default=True)
    limits = _limits(session, users=5)

    with use_tenant(None):  # ty: ignore[invalid-argument-type]
        limits.ensure_room(PlanResource.USERS)


# Public API


def test_a_plan_without_the_public_api_gives_no_scope(session):
    _plan(session, "basico", public_api=False)
    _subscribe(session, "basico")

    plan = SubscriptionIntegrationPlan(_tenant_plan(session), SubscriptionSettings())

    assert plan.allowed_scopes() == frozenset()
    assert SubscriptionIntegrationPlan(
        _tenant_plan(session), SubscriptionSettings(enforcement_enabled=False)
    ).allowed_scopes() == frozenset(Scope)


def test_a_plan_with_the_public_api_gives_every_scope(session):
    _plan(session, "profesional", is_default=True)

    plan = SubscriptionIntegrationPlan(_tenant_plan(session), SubscriptionSettings())

    assert plan.allowed_scopes() == frozenset(Scope)


# Monthly documents


def _count(session: Session, kind: DocumentKind, at: datetime) -> dict:
    return CountDocumentCommandHandler(
        SqlAlchemyDocumentUsageRepository(session), _tenant_plan(session)
    ).handle(CountDocumentCommand(kind, at))


def test_each_authorized_document_counts_in_its_month(session):
    november = datetime(2026, 11, 30, 23, 0, tzinfo=UTC)  # 18:00 in Ecuador
    december = datetime(2026, 12, 1, 6, 0, tzinfo=UTC)

    _count(session, DocumentKind.INVOICE, november)
    _count(session, DocumentKind.INVOICE, november)
    _count(session, DocumentKind.CREDIT_NOTE, november)
    result = _count(session, DocumentKind.INVOICE, december)

    months = SqlAlchemyDocumentUsageRepository(session).months(
        [date(2026, 10, 1), date(2026, 11, 1), date(2026, 12, 1)]
    )
    assert [(m.invoices, m.credit_notes, m.total) for m in months] == [
        (0, 0, 0),
        (2, 1, 3),
        (1, 0, 1),
    ]
    assert result == {"period": date(2026, 12, 1), "invoices": 1, "credit_notes": 0}


def test_another_tenants_documents_never_count(session):
    at = datetime(2026, 11, 10, tzinfo=UTC)
    with use_tenant(OTHER_TENANT):
        _count(session, DocumentKind.INVOICE, at)

    (month,) = SqlAlchemyDocumentUsageRepository(session).months([date(2026, 11, 1)])

    assert month.total == 0


def test_the_first_document_beyond_the_plan_is_logged_once(session, json_logs):
    _plan(session, "basico", limits={"max_monthly_documents": 1}, is_default=True)
    at = datetime(2026, 11, 10, tzinfo=UTC)

    for _ in range(3):
        _count(session, DocumentKind.INVOICE, at)

    exceeded = json_logs.event("plan_documents_limit_exceeded")
    assert len(exceeded) == 1
    assert (exceeded[0]["period"], exceeded[0]["limit"]) == ("2026-11-01", 1)


# Queries


def test_the_usage_screen_shows_each_limit_and_the_last_six_months(session):
    _plan(
        session,
        "basico",
        limits={"max_branches": 1, "max_monthly_documents": 300},
        is_default=True,
    )
    _count(session, DocumentKind.INVOICE, datetime.now(UTC))

    result = GetSubscriptionQueryHandler(
        _tenant_plan(session),
        CountedUsage(branches=1, users=4),
        SqlAlchemyDocumentUsageRepository(session),
        SubscriptionSettings(),
    ).handle(GetSubscriptionQuery())

    assert result["plan"]["code"] == "basico"
    assert (result["status"], result["read_only"]) == (SubscriptionStatus.ACTIVE, False)
    usage = {u["resource"]: (u["used"], u["limit"]) for u in result["resources"]}
    assert usage[PlanResource.BRANCHES] == (1, 1)
    assert usage[PlanResource.USERS] == (4, None)
    assert result["documents"]["limit"] == 300
    assert len(result["documents"]["months"]) == 6
    assert result["documents"]["months"][-1]["total"] == 1


@pytest.mark.parametrize(
    ("enforced", "read_only"), [(True, True), (False, False)], ids=["on", "off"]
)
def test_a_suspended_tenant_sees_it_is_read_only(session, enforced, read_only):
    _plan(session, "basico", limits={"max_monthly_documents": 1}, is_default=True)
    _subscribe(session)
    _change(session, status=SubscriptionStatus.SUSPENDED)
    _count(session, DocumentKind.INVOICE, datetime.now(UTC))

    result = GetSubscriptionStatusQueryHandler(
        _tenant_plan(session),
        SqlAlchemyDocumentUsageRepository(session),
        SubscriptionSettings(enforcement_enabled=enforced),
    ).handle(GetSubscriptionStatusQuery())

    assert result == {
        "plan_name": "Basico",
        "status": SubscriptionStatus.SUSPENDED,
        "trial_ends_at": None,
        "read_only": read_only,
        "documents_limit_reached": True,
    }
