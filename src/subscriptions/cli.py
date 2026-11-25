"""Platform commands for plans and subscriptions (S8.4). They run as
faclab_worker; the HTTP console arrives with the platform role (S8.5).

A limit is a number or `unlimited`. Every change of a subscription records who
made it (`--by`, required) on the row and in the log. The API sees a change of
status within SUBSCRIPTION_STATUS_CACHE_SECONDS.

Usage:
    python -m src.subscriptions.cli plans
    python -m src.subscriptions.cli plan-create CODE --name NAME [--max-branches N]
        [--max-terminals N] [--max-users N] [--max-integration-clients N]
        [--max-webhook-endpoints N] [--max-monthly-documents N]
        [--no-public-api] [--default]
    python -m src.subscriptions.cli plan-update CODE [--name NAME] [--max-... N|unlimited]
        [--public-api | --no-public-api] [--active | --inactive] [--default]
    python -m src.subscriptions.cli subscription --ruc RUC
    python -m src.subscriptions.cli subscription-set --ruc RUC [--plan CODE]
        [--status trial|active|suspended|cancelled] [--trial-days N] --by NAME
"""

import argparse
import sys
from collections.abc import Callable
from typing import Any, TypeVar

from sqlalchemy import select

import src
from config import config
from src.container import create_wireup_container
from src.shared.domain.exceptions import BaseError
from src.shared.domain.tenant import TenantContext, TenantSource
from src.shared.infra.database import worker_session_maker
from src.shared.infra.events.scope import create_sync_scope
from src.shared.infra.logging import configure_logging
from src.subscriptions.app.commands.plans import (
    CreatePlanCommand,
    CreatePlanCommandHandler,
    UpdatePlanCommand,
    UpdatePlanCommandHandler,
    describe_plan,
)
from src.subscriptions.app.commands.subscriptions import (
    ChangeSubscriptionCommand,
    ChangeSubscriptionCommandHandler,
)
from src.subscriptions.app.queries.subscription import (
    GetSubscriptionQuery,
    GetSubscriptionQueryHandler,
)
from src.subscriptions.app.repositories import PlanRepository
from src.subscriptions.domain.entities import SubscriptionStatus
from src.tenancy.infra.models import TenantModel

LIMITS = (
    "max_branches",
    "max_terminals",
    "max_users",
    "max_integration_clients",
    "max_webhook_endpoints",
    "max_monthly_documents",
)


def _limit(value: str) -> int | None:
    if value == "unlimited":
        return None
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("a number or 'unlimited'") from None
    if number < 0:
        raise argparse.ArgumentTypeError("0 or more")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.subscriptions.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("plans", help="List the plans")

    create = commands.add_parser("plan-create", help="Create a plan")
    create.add_argument("code")
    create.add_argument("--name", required=True)
    update = commands.add_parser("plan-update", help="Change a plan")
    update.add_argument("code")
    update.add_argument("--name")
    for sub in (create, update):
        for limit in LIMITS:
            # An update changes only the limits given
            extra = {"default": argparse.SUPPRESS} if sub is update else {}
            sub.add_argument(f"--{limit.replace('_', '-')}", type=_limit, **extra)
        sub.add_argument("--default", action="store_true", help="New tenants get it")
    create.add_argument("--no-public-api", action="store_true")
    update.add_argument(
        "--public-api", action=argparse.BooleanOptionalAction, default=None
    )
    update.add_argument("--active", action=argparse.BooleanOptionalAction, default=None)

    show = commands.add_parser("subscription", help="A tenant's plan and usage")
    show.add_argument("--ruc", required=True)

    change = commands.add_parser(
        "subscription-set", help="Change a tenant's plan or status"
    )
    change.add_argument("--ruc", required=True)
    change.add_argument("--plan")
    change.add_argument("--status", choices=[s.value for s in SubscriptionStatus])
    change.add_argument("--trial-days", type=int)
    change.add_argument("--by", required=True, help="Who changes it (audit)")
    return parser


T = TypeVar("T")


def _run(action: Callable[[Any], T], tenant: TenantContext | None = None) -> T:
    """Runs in one faclab_worker transaction, in `tenant` when given"""
    if src.wireup_container is None:
        src.wireup_container = create_wireup_container()
    with worker_session_maker()() as session:
        with create_sync_scope(session, tenant=tenant) as scope:
            result = action(scope)
        session.commit()
    return result


def _tenant(ruc: str) -> TenantContext | None:
    with worker_session_maker()() as session:
        tenant_id = session.scalar(select(TenantModel.id).where(TenantModel.ruc == ruc))
    if tenant_id is None:
        return None
    return TenantContext(tenant_id, TenantSource.TASK)


def _print(values: dict) -> None:
    for key, value in values.items():
        print(f"{key}\t{'unlimited' if value is None and key in LIMITS else value}")


def _plans(scope: Any) -> list:
    return [describe_plan(plan) for plan in scope.get(PlanRepository).get_all()]


def main(argv: list[str] | None = None) -> int:
    configure_logging(log_level=config.LOG_LEVEL)
    args = _parser().parse_args(argv)
    try:
        return _main(args)
    except BaseError as exc:
        print(f"{exc.error_code}: {exc}", file=sys.stderr)
        return 1


def _main(args: argparse.Namespace) -> int:
    if args.command == "plans":
        for plan in _run(_plans):
            limits = " ".join(
                f"{name[4:]}={plan[name] if plan[name] is not None else '-'}"
                for name in LIMITS
            )
            flags = [
                flag
                for flag, on in (
                    ("default", plan["is_default"]),
                    ("inactive", not plan["is_active"]),
                    ("no-public-api", not plan["public_api"]),
                )
                if on
            ]
            print(f"{plan['code']}\t{plan['name']}\t{limits}\t{','.join(flags)}")
        return 0

    if args.command in ("plan-create", "plan-update"):
        limits = {name: getattr(args, name) for name in LIMITS if hasattr(args, name)}
        if args.command == "plan-create":
            command = CreatePlanCommand(
                code=args.code,
                name=args.name,
                limits=limits,
                public_api=not args.no_public_api,
                is_default=args.default,
            )
            _print(
                _run(lambda scope: scope.get(CreatePlanCommandHandler).handle(command))
            )
            return 0
        # Only what was given changes; `unlimited` removes a limit
        changes: dict[str, Any] = dict(limits)
        for name, value in (
            ("name", args.name),
            ("public_api", args.public_api),
            ("is_active", args.active),
            ("is_default", True if args.default else None),
        ):
            if value is not None:
                changes[name] = value
        update = UpdatePlanCommand(code=args.code, changes=changes)
        _print(_run(lambda scope: scope.get(UpdatePlanCommandHandler).handle(update)))
        return 0

    tenant = _tenant(args.ruc)
    if tenant is None:
        print(f"No tenant with RUC {args.ruc}", file=sys.stderr)
        return 1
    if args.command == "subscription":
        result = _run(
            lambda scope: scope.get(GetSubscriptionQueryHandler).handle(
                GetSubscriptionQuery()
            ),
            tenant,
        )
        print(f"plan\t{(result['plan'] or {}).get('code')}")
        print(f"status\t{result['status']}\ttrial_ends_at\t{result['trial_ends_at']}")
        print(f"read_only\t{result['read_only']}")
        for usage in result["resources"]:
            limit = usage["limit"] if usage["limit"] is not None else "unlimited"
            print(f"{usage['resource']}\t{usage['used']}/{limit}")
        for month in result["documents"]["months"]:
            print(f"documents {month['period']:%Y-%m}\t{month['total']}")
        return 0

    if args.plan is None and args.status is None:
        print("Give --plan, --status or both", file=sys.stderr)
        return 2
    change = ChangeSubscriptionCommand(
        by=args.by,
        plan_code=args.plan,
        status=SubscriptionStatus(args.status) if args.status else None,
        trial_days=args.trial_days,
    )
    _print(
        _run(
            lambda scope: scope.get(ChangeSubscriptionCommandHandler).handle(change),
            tenant,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
