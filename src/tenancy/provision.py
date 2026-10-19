"""Alta de una empresa con su primer administrador y su estructura mínima
(matriz 001, punto de emisión 001, bodega, ubicación y terminal). Idempotente.

Usage:
    PROVISION_ADMIN_PASSWORD=... python -m src.tenancy.provision \\
        --ruc 1799999990001 --legal-name "Ferretería Ejemplo S.A." \\
        [--trade-name "Ferretería Ejemplo"] \\
        --admin-username ana --admin-email ana@example.com \\
        [--admin-full-name "Ana Pérez"] [--branch-address "Av. Amazonas N24"]

The password goes in the environment, never in the arguments (shell history,
process list). It is only needed when the admin user doesn't exist yet; an
existing user is added to the tenant with its current password.
"""

import argparse
import sys

import structlog
from environs import Env

import src
from src.container import create_wireup_container
from src.shared.domain.exceptions import BaseError
from src.shared.domain.tenant import TenantContext, TenantSource
from src.shared.infra.events.scope import create_sync_scope
from src.tenancy.app.commands.provision_tenant import (
    ProvisionTenantCommand,
    ProvisionTenantCommandHandler,
)
from src.tenancy.app.commands.set_up_structure import (
    SetUpTenantStructureCommand,
    SetUpTenantStructureCommandHandler,
)

logger = structlog.get_logger(__name__)


def provision(
    command: ProvisionTenantCommand, branch_address: str | None = None
) -> dict:
    """Creates the tenant and its admin in one transaction, then its structure
    in another one inside the tenant: `SET LOCAL app.tenant_id` (row-level
    security) only applies when a transaction begins. A rerun completes what
    a failed one left."""
    if src.wireup_container is None:
        src.wireup_container = create_wireup_container()
    with create_sync_scope() as scope:
        result = scope.get(ProvisionTenantCommandHandler).handle(command)
    tenant = TenantContext(result["tenant_id"], TenantSource.TASK)
    with create_sync_scope(tenant=tenant) as scope:
        structure = scope.get(SetUpTenantStructureCommandHandler).handle(
            SetUpTenantStructureCommand(branch_address=branch_address)
        )
    return {**result, **structure}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.tenancy.provision",
        description="Create a tenant and its first admin (idempotent)",
    )
    parser.add_argument("--ruc", required=True)
    parser.add_argument("--legal-name", required=True)
    parser.add_argument("--trade-name")
    parser.add_argument("--admin-username", required=True)
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--admin-full-name")
    parser.add_argument("--branch-address", help="Address of the main branch")
    args = parser.parse_args(argv)

    env = Env()
    env.read_env()
    command = ProvisionTenantCommand(
        ruc=args.ruc,
        legal_name=args.legal_name,
        trade_name=args.trade_name,
        admin_username=args.admin_username,
        admin_email=args.admin_email,
        admin_password=env.str("PROVISION_ADMIN_PASSWORD", "") or None,
        admin_full_name=args.admin_full_name,
    )
    try:
        result = provision(command, branch_address=args.branch_address)
    except BaseError as exc:
        logger.error(
            "tenant_provision_failed", error_code=exc.error_code, error=str(exc)
        )
        return 1

    logger.info(
        "tenant_provisioned",
        tenant_id=str(result["tenant_id"]),
        ruc=args.ruc,
        tenant_created=result["tenant_created"],
        admin_username=args.admin_username,
        user_created=result["user_created"],
        membership_created=result["membership_created"],
        structure_created=result["structure_created"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
