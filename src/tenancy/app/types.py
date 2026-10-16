from dataclasses import dataclass

from src.tenancy.domain.entities import Membership, Tenant


@dataclass(frozen=True)
class TenantAccess:
    """Una empresa a la que el usuario puede entrar y su membresía en ella"""

    tenant: Tenant
    membership: Membership
