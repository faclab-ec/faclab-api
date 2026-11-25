"""Termination of a company's contract, from the platform's CLI (S8.7,
docs/offboarding-runbook.md). Anonymizing and purging are destructive and never
go over HTTP. Every command takes the company's RUC and `--by` (who does it, for
the log and the audit entry), and anonymize and purge write nothing without
`--execute`: without it they print what they would do.

Usage:
    python -m src.data_protection.cli plan --ruc R --by NAME
    python -m src.data_protection.cli start --ruc R --by NAME
    python -m src.data_protection.cli cancel --ruc R --by NAME
    python -m src.data_protection.cli anonymize --ruc R --by NAME [--execute] [--skip-grace]
    python -m src.data_protection.cli purge --ruc R --by NAME --confirm-ruc R [--execute]
"""

import argparse
import json
import sys
from uuid import UUID

import structlog
from sqlalchemy import select

import src
from config import config
from src.container import create_wireup_container
from src.data_protection.app.commands.offboarding import (
    AnonymizeTenantCommand,
    AnonymizeTenantCommandHandler,
    CancelOffboardingCommand,
    CancelOffboardingCommandHandler,
    PurgeTenantCommand,
    PurgeTenantCommandHandler,
    StartOffboardingCommand,
    StartOffboardingCommandHandler,
)
from src.data_protection.app.offboarding import TenantDataCleaner
from src.shared.domain.tenant import TenantContext, TenantSource
from src.shared.infra.database import worker_session_maker
from src.shared.infra.events.scope import create_sync_scope
from src.shared.infra.logging import configure_logging
from src.tenancy.infra.models import TenantModel

logger = structlog.get_logger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.data_protection.cli",
        description="Offboarding of a company: grace period, anonymization, purge",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (
        ("plan", "What anonymizing and purging would do, and what stays"),
        ("start", "Cancel the subscription and start the grace period"),
        ("cancel", "Take the offboarding back (only while the data is whole)"),
        ("anonymize", "Delete what tax law doesn't need, anonymize the rest"),
        ("purge", "Delete everything of the company (after the tax retention)"),
    ):
        command = commands.add_parser(name, help=text)
        command.add_argument("--ruc", required=True)
        command.add_argument("--by", required=True, help="Who does it (log, audit)")
        if name in ("anonymize", "purge"):
            command.add_argument(
                "--execute", action="store_true", help="Write: without it, a plan"
            )
        if name == "anonymize":
            command.add_argument(
                "--skip-grace",
                action="store_true",
                help="Don't wait for the grace period (a test company)",
            )
        if name == "purge":
            command.add_argument(
                "--confirm-ruc", required=True, help="The RUC again: no undo"
            )
    return parser


def _find(ruc: str) -> UUID:
    with worker_session_maker()() as session:
        tenant_id = session.scalar(select(TenantModel.id).where(TenantModel.ruc == ruc))
    if tenant_id is None:
        raise SystemExit(f"No company with RUC {ruc}")
    return tenant_id


def _context(tenant_id, by: str) -> TenantContext:
    return TenantContext(tenant_id, TenantSource.TASK, user_name=by)


def _show(value) -> None:
    print(json.dumps(value, indent=2, default=lambda v: v.isoformat()))


def run(args: argparse.Namespace) -> dict:
    tenant_id = _find(args.ruc)
    context = _context(tenant_id, args.by)
    with worker_session_maker()() as session:
        with create_sync_scope(session, tenant=context) as scope:
            if args.command == "plan":
                result = scope.get(TenantDataCleaner).plan(tenant_id)
            elif args.command == "start":
                result = scope.get(StartOffboardingCommandHandler).handle(
                    StartOffboardingCommand(
                        grace_days=config.OFFBOARDING_GRACE_DAYS,
                        retention_years=config.TAX_RETENTION_YEARS,
                    )
                )
            elif args.command == "cancel":
                result = scope.get(CancelOffboardingCommandHandler).handle(
                    CancelOffboardingCommand()
                )
            elif args.command == "anonymize":
                if not args.execute:
                    return scope.get(TenantDataCleaner).plan(tenant_id)
                result = scope.get(AnonymizeTenantCommandHandler).handle(
                    AnonymizeTenantCommand(skip_grace=args.skip_grace)
                )
            else:
                if not args.execute:
                    return scope.get(TenantDataCleaner).plan(tenant_id)
                result = scope.get(PurgeTenantCommandHandler).handle(
                    PurgeTenantCommand(confirm_ruc=args.confirm_ruc)
                )
        session.commit()
    return result


def main(argv: list[str] | None = None) -> int:
    configure_logging(log_level=config.LOG_LEVEL)
    args = _parser().parse_args(argv)
    if src.wireup_container is None:
        src.wireup_container = create_wireup_container()
    _show(run(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
