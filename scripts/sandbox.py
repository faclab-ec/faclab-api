"""Empresa de sandbox para un integrador (S6.5): datos ficticios y,
opcionalmente, un cliente de integración con todos los scopes.

Crea la empresa con su administrador (el mismo aprovisionamiento que
`make provision-tenant`) y le carga el catálogo del seed local: tres
sucursales con su punto de emisión, bodega y caja, productos con
presentaciones y stock, listas de precios, clientes, proveedores y algunas
ventas. Todo es inventado; las identificaciones tienen dígito verificador
válido, pero no son de nadie.

Solo corre en el despliegue del sandbox: se niega con ENVIRONMENT=production
y cuando INTEGRATION_ENVIRONMENT no es `sandbox`. Los clientes que crea son
`fl_test_` y solo reciben tokens de ese despliegue.

Idempotente: una empresa que ya tiene productos no se toca, salvo con
`--reset`, que reemplaza sus datos de negocio (no sus clientes de integración
ni sus webhooks). Cada `--client-name` crea un cliente nuevo.

Usage:
    PROVISION_ADMIN_PASSWORD=... python -m scripts.sandbox \\
        --ruc 0999999980001 --legal-name "Tienda Demo (sandbox)" \\
        --admin-username tienda-demo --admin-email dev@tienda.example \\
        [--client-name "Tienda en línea"] [--credentials-file ruta] [--reset]

Sin `--credentials-file`, el secreto del cliente se imprime una sola vez; con
él, se escribe en ese archivo (permisos 0600) como FACLAB_CLIENT_ID y
FACLAB_CLIENT_SECRET y no aparece en la salida.
"""

import argparse
import os
import sys
from pathlib import Path
from uuid import UUID

import structlog
from environs import Env
from sqlalchemy import delete, func, select

import src
from scripts import seed
from src.auth.domain.scopes import Scope
from src.catalog.product.infra.models import ProductModel
from src.container import create_wireup_container
from src.integrations.app.commands.clients import (
    CreateIntegrationClientCommand,
    CreateIntegrationClientCommandHandler,
)
from src.invoicing.infra.models import CreditNoteModel, InvoiceDiscrepancyModel
from src.shared.domain.exceptions import BaseError
from src.shared.domain.tenant import TenantContext, TenantSource
from src.shared.infra.events.scope import create_sync_scope
from src.shared.infra.tenant import tenant_scope
from src.tenancy.app.commands.provision_tenant import ProvisionTenantCommand
from src.tenancy.provision import provision
from src.webhooks.infra.models import WebhookStockChangeModel

logger = structlog.get_logger(__name__)

# Lo que la API pública y los webhooks dejan en la empresa, antes de lo que el
# seed borra: notas de crédito y discrepancias apuntan a las ventas, y los
# cambios de stock pendientes de avisar, a productos y ubicaciones
SANDBOX_TRUNCATE_ORDER = [
    CreditNoteModel,
    InvoiceDiscrepancyModel,
    WebhookStockChangeModel,
    *seed.TRUNCATE_ORDER,
]

OPERATOR_STEPS = """
Para facturar en el ambiente de pruebas del SRI, en faclab-invoicing (con un
usuario administrador de esta empresa):
  1. Perfil fiscal (PUT /api/company-config) con environment 1 (pruebas).
  2. Certificado .p12 del RUC {ruc} (POST /api/certificates) y elegirlo
     en el perfil (signingCertId).
  3. GET /api/invoicing/status debe responder listo.
Sin eso, las ventas quedan con su factura pendiente; el resto de la API
funciona igual.
"""


def ensure_sandbox_deployment() -> None:
    """Never against production: the deployment must be the sandbox's"""
    env = Env()
    env.read_env()
    environment = env("ENVIRONMENT", "local")
    default = "production" if environment == "production" else "sandbox"
    integration_environment = env("INTEGRATION_ENVIRONMENT", default)
    if environment == "production" or integration_environment != "sandbox":
        raise SystemExit(
            "El sandbox solo se crea en el despliegue del sandbox "
            "(INTEGRATION_ENVIRONMENT=sandbox y ENVIRONMENT distinto de "
            f"production; actual: {environment}, {integration_environment})"
        )


def has_business_data(tenant_id: UUID) -> bool:
    factory = seed.get_session_maker()
    with (
        tenant_scope(TenantContext(tenant_id, TenantSource.TASK)),
        factory() as session,
    ):
        products = session.execute(
            select(func.count())
            .select_from(ProductModel)
            .where(ProductModel.tenant_id == tenant_id)
        ).scalar_one()
    return products > 0


def load_data(tenant_id: UUID) -> None:
    """Replaces the tenant's business rows (the provisioned structure
    included) with the seed's catalog, in one transaction in its context"""
    factory = seed.get_session_maker()
    with (
        tenant_scope(TenantContext(tenant_id, TenantSource.TASK)),
        factory() as session,
    ):
        for model in SANDBOX_TRUNCATE_ORDER:
            session.execute(delete(model).where(model.tenant_id == tenant_id))
        session.flush()
        seed.seed_tenant(session)
        session.commit()


def create_client(tenant_id: UUID, name: str) -> dict:
    """A client with every scope and every branch, like an integrator's
    first one; the result carries its secret"""
    if src.wireup_container is None:
        src.wireup_container = create_wireup_container()
    tenant = TenantContext(tenant_id, TenantSource.TASK)
    with create_sync_scope(tenant=tenant) as scope:
        return scope.get(CreateIntegrationClientCommandHandler).handle(
            CreateIntegrationClientCommand(name=name, scopes=list(Scope))
        )


def write_credentials(path: Path, client: dict) -> None:
    """Only the owner reads it; an existing file is replaced"""
    content = (
        f"FACLAB_CLIENT_ID={client['client_id']}\n"
        f"FACLAB_CLIENT_SECRET={client['client_secret']}\n"
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(content)
    os.chmod(path, 0o600)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.sandbox",
        description="Create a sandbox company with made-up data (idempotent)",
    )
    parser.add_argument("--ruc", required=True)
    parser.add_argument("--legal-name", required=True)
    parser.add_argument("--trade-name")
    parser.add_argument("--admin-username", required=True)
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--admin-full-name")
    parser.add_argument(
        "--client-name", help="Also create an integration client with every scope"
    )
    parser.add_argument(
        "--credentials-file",
        type=Path,
        help="Write the client's id and secret here (0600) instead of printing",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Replace the business data of a company that already has it",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.credentials_file and not args.client_name:
        print("--credentials-file needs --client-name", file=sys.stderr)
        return 2
    ensure_sandbox_deployment()

    env = Env()
    env.read_env()
    try:
        result = provision(
            ProvisionTenantCommand(
                ruc=args.ruc,
                legal_name=args.legal_name,
                trade_name=args.trade_name,
                admin_username=args.admin_username,
                admin_email=args.admin_email,
                admin_password=env.str("PROVISION_ADMIN_PASSWORD", "") or None,
                admin_full_name=args.admin_full_name,
            )
        )
    except BaseError as exc:
        logger.error(
            "sandbox_provision_failed", error_code=exc.error_code, error=str(exc)
        )
        return 1
    tenant_id = result["tenant_id"]

    loaded = args.reset or not has_business_data(tenant_id)
    if loaded:
        print(f"Empresa de sandbox {tenant_id}: cargando datos ficticios")
        load_data(tenant_id)
    else:
        print(
            f"Empresa de sandbox {tenant_id}: ya tiene datos, no se tocan "
            "(--reset los reemplaza)"
        )

    client = create_client(tenant_id, args.client_name) if args.client_name else None
    logger.info(
        "sandbox_ready",
        tenant_id=str(tenant_id),
        ruc=args.ruc,
        tenant_created=result["tenant_created"],
        data_loaded=loaded,
        client_id=client["client_id"] if client else None,
    )

    if client and args.credentials_file:
        write_credentials(args.credentials_file, client)
        print(f"Cliente {client['client_id']}: credenciales en {args.credentials_file}")
    elif client:
        print(
            f"\nCliente de integración {client['client_id']}\n"
            f"Secreto (se muestra esta única vez): {client['client_secret']}\n"
        )
    print(OPERATOR_STEPS.format(ruc=args.ruc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
