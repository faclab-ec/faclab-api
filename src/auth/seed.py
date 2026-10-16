"""Bootstrap the default tenant and its first admin. Idempotent.

Usage:
    AUTH_SEED_USERNAME=admin \\
    AUTH_SEED_EMAIL=admin@faclab.local \\
    AUTH_SEED_PASSWORD=ChangeMe123! \\
    [AUTH_SEED_TENANT_RUC=1799999990001] \\
    [AUTH_SEED_TENANT_NAME="Empresa de prueba"] \\
    python -m src.auth.seed

The tenant settings have local defaults (a made-up RUC); staging and production
require them. More tenants: `python -m src.tenancy.provision`.
"""

import sys

import structlog
from environs import Env

from src.shared.domain.exceptions import BaseError
from src.tenancy.app.commands.provision_tenant import ProvisionTenantCommand
from src.tenancy.provision import provision

logger = structlog.get_logger(__name__)

# Valid check digit, made up: no real company
LOCAL_TENANT_RUC = "1799999990001"
LOCAL_TENANT_NAME = "Empresa de prueba"


def main() -> int:
    env = Env()
    env.read_env()
    if env("ENVIRONMENT", "local") == "local":
        ruc = env("AUTH_SEED_TENANT_RUC", LOCAL_TENANT_RUC)
        legal_name = env("AUTH_SEED_TENANT_NAME", LOCAL_TENANT_NAME)
    else:
        ruc = env("AUTH_SEED_TENANT_RUC")
        legal_name = env("AUTH_SEED_TENANT_NAME")
    username = env("AUTH_SEED_USERNAME")
    command = ProvisionTenantCommand(
        ruc=ruc,
        legal_name=legal_name,
        admin_username=username,
        admin_email=env("AUTH_SEED_EMAIL"),
        admin_password=env("AUTH_SEED_PASSWORD"),
    )

    try:
        result = provision(command)
    except BaseError as exc:
        logger.error("auth_seed_failed", error_code=exc.error_code, error=str(exc))
        return 1

    logger.info(
        "auth_seed_done",
        tenant_id=str(result["tenant_id"]),
        tenant_created=result["tenant_created"],
        username=username,
        user_created=result["user_created"],
        membership_created=result["membership_created"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
