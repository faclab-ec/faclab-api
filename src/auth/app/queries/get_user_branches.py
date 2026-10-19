from dataclasses import dataclass
from uuid import UUID

from wireup import injectable

from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError
from src.tenancy.app.repositories import MembershipRepository


@dataclass
class GetUserBranchesQuery(Query):
    tenant_id: UUID
    user_id: int = 0


@injectable(lifetime="scoped")
class GetUserBranchesQueryHandler(QueryHandler[GetUserBranchesQuery, dict]):
    """Las sucursales a las que el usuario está limitado en la empresa; vacío
    si puede entrar a todas"""

    def __init__(self, memberships: MembershipRepository):
        self.memberships = memberships

    def _handle(self, query: GetUserBranchesQuery) -> dict:
        membership = self.memberships.get_for(query.tenant_id, query.user_id)
        if membership is None:
            raise NotFoundError(f"User with id {query.user_id} not found")
        return {
            "user_id": query.user_id,
            "branch_ids": self.memberships.branch_ids(membership.require_id()),
        }
