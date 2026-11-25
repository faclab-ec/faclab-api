"""The platform CLI of plans and subscriptions, on SQLite (S8.4)."""

import pytest
from sqlalchemy import select

import src
from src.auth.infra.models import UserModel
from src.container import create_wireup_container
from src.integrations.infra.models import IntegrationClientModel
from src.organization.infra.models import BranchModel, PosTerminalModel
from src.shared.domain.tenant import use_tenant
from src.shared.infra.database import Base, create_session_maker
from src.subscriptions import cli
from src.subscriptions.infra.models import (
    DocumentUsageModel,
    PlanModel,
    SubscriptionModel,
)
from src.tenancy.infra.models import MembershipModel, TenantModel
from src.webhooks.infra.models import WebhookEndpointModel
from tests.conftest import TEST_TENANT_ID
from tests.sqlite import load_all_models

# Every table, for the foreign keys of the ones created
load_all_models()

RUC = "1799999990001"


@pytest.fixture
def factory(monkeypatch):
    """The CLI's faclab_worker sessions, on SQLite"""
    factory = create_session_maker("sqlite://")
    Base.metadata.create_all(
        factory.kw["bind"],
        tables=[
            Base.metadata.tables[model.__tablename__]
            for model in (
                TenantModel,
                PlanModel,
                SubscriptionModel,
                DocumentUsageModel,
                BranchModel,
                PosTerminalModel,
                UserModel,
                MembershipModel,
                IntegrationClientModel,
                WebhookEndpointModel,
            )
        ],
    )
    with factory() as session:
        session.add(TenantModel(id=TEST_TENANT_ID, ruc=RUC, legal_name="Empresa"))
        session.commit()
    monkeypatch.setattr(cli, "worker_session_maker", lambda: factory)
    monkeypatch.setattr(src, "wireup_container", create_wireup_container())
    with use_tenant(None):  # ty: ignore[invalid-argument-type]
        yield factory


def _plan(factory, code: str) -> PlanModel:
    with factory() as session:
        return session.scalars(select(PlanModel).where(PlanModel.code == code)).one()


def test_the_platform_creates_and_lists_plans(factory, capsys):
    assert (
        cli.main(["plan-create", "ilimitado", "--name", "Sin límites", "--default"])
        == 0
    )
    assert (
        cli.main(
            [
                "plan-create",
                "basico",
                "--name",
                "Básico",
                "--max-branches",
                "1",
                "--max-monthly-documents",
                "300",
                "--no-public-api",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert cli.main(["plans"]) == 0

    out = capsys.readouterr().out
    assert "ilimitado\tSin límites\tbranches=- " in out
    assert "basico\tBásico\tbranches=1 " in out
    assert "monthly_documents=300\tno-public-api" in out
    basico = _plan(factory, "basico")
    assert (basico.max_branches, basico.max_terminals, basico.public_api) == (
        1,
        None,
        False,
    )


def test_an_update_changes_only_the_limits_given(factory):
    cli.main(
        [
            "plan-create",
            "basico",
            "--name",
            "B",
            "--max-branches",
            "1",
            "--max-users",
            "3",
        ]
    )

    assert cli.main(["plan-update", "basico", "--max-branches", "unlimited"]) == 0

    basico = _plan(factory, "basico")
    assert (basico.max_branches, basico.max_users) == (None, 3)


def test_the_platform_suspends_a_tenant_and_sees_its_usage(factory, capsys):
    cli.main(["plan-create", "ilimitado", "--name", "Sin límites", "--default"])
    cli.main(["plan-create", "basico", "--name", "Básico", "--max-branches", "1"])

    assert (
        cli.main(
            [
                "subscription-set",
                "--ruc",
                RUC,
                "--plan",
                "basico",
                "--status",
                "suspended",
                "--by",
                "ops",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert cli.main(["subscription", "--ruc", RUC]) == 0

    out = capsys.readouterr().out
    assert "plan\tbasico" in out
    assert "status\tsuspended" in out
    assert "read_only\tTrue" in out
    assert "branches\t0/1" in out
    assert "users\t0/unlimited" in out
    with factory() as session:
        subscription = session.scalars(select(SubscriptionModel)).one()
    assert (subscription.status, subscription.status_changed_by) == ("suspended", "ops")


def test_a_change_needs_a_plan_or_a_status(factory):
    assert cli.main(["subscription-set", "--ruc", RUC, "--by", "ops"]) == 2


def test_an_unknown_tenant_or_plan_fails(factory, capsys):
    assert cli.main(["subscription", "--ruc", "0999999999001"]) == 1
    assert (
        cli.main(["subscription-set", "--ruc", RUC, "--plan", "x", "--by", "ops"]) == 1
    )
    assert "DEFAULT_PLAN_REQUIRED" in capsys.readouterr().err


def test_a_limit_is_a_number_or_unlimited(factory):
    with pytest.raises(SystemExit):
        cli.main(["plan-create", "basico", "--name", "B", "--max-users", "muchos"])
