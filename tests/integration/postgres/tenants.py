"""Tenants for the Postgres integration tests."""

from uuid import UUID, uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from src.tenancy.infra.models import TenantModel

# Made up, with valid check digits
DEFAULT_TENANT_RUC = "1799999990001"
OTHER_TENANT_RUC = "0999999999001"


def ensure_tenant(
    engine: Engine, ruc: str = DEFAULT_TENANT_RUC, legal_name: str | None = None
) -> UUID:
    """The id of the tenant with that RUC, created if missing"""
    with Session(bind=engine) as session:
        tenant_id = session.scalar(select(TenantModel.id).where(TenantModel.ruc == ruc))
        if tenant_id is None:
            tenant_id = uuid4()
            session.add(
                TenantModel(
                    id=tenant_id,
                    ruc=ruc,
                    legal_name=legal_name or f"Empresa {ruc}",
                    status="active",
                )
            )
            session.commit()
        return tenant_id
