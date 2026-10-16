from dataclasses import dataclass
from uuid import UUID

from wireup import injectable

from src.shared.app.queries import Query, QueryHandler
from src.tenancy.app.repositories import MembershipRepository, TenantRepository
from src.tenancy.domain.exceptions import TenantNotFoundError


@dataclass
class GetMyTenantsQuery(Query):
    """La empresa de la sesión y las empresas a las que el usuario puede
    cambiar"""

    tenant_id: UUID
    user_id: int = 0


@injectable(lifetime="scoped")
class GetMyTenantsQueryHandler(QueryHandler[GetMyTenantsQuery, dict]):
    def __init__(self, tenants: TenantRepository, memberships: MembershipRepository):
        self.tenants = tenants
        self.memberships = memberships

    def _handle(self, query: GetMyTenantsQuery) -> dict:
        tenant = self.tenants.get(query.tenant_id)
        if tenant is None:
            raise TenantNotFoundError()
        return {
            "tenant": tenant.dict(),
            "tenants": [
                {**access.tenant.dict(), "role": access.membership.role}
                for access in self.memberships.active_accesses(query.user_id)
            ],
        }
