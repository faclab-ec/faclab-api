from dataclasses import dataclass
from uuid import UUID

from wireup import injectable

from src.auth.app.repositories import UserRepository
from src.auth.domain.entities import Role
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class ListUsersQuery(Query):
    """Los usuarios de la empresa; `is_active` y `role` son los de su
    membresía en ella"""

    tenant_id: UUID
    is_active: bool | None = None
    role: int | None = None
    limit: int | None = None
    offset: int | None = None


@injectable(lifetime="scoped")
class ListUsersQueryHandler(QueryHandler[ListUsersQuery, dict]):
    def __init__(self, repo: UserRepository):
        self.repo = repo

    def _handle(self, query: ListUsersQuery) -> dict:
        return self.repo.paginate_members(
            query.tenant_id,
            role=Role(query.role) if query.role is not None else None,
            is_active=query.is_active,
            limit=query.limit,
            offset=query.offset,
        )


@dataclass
class GetUserByIdQuery(Query):
    tenant_id: UUID
    user_id: int = 0


@injectable(lifetime="scoped")
class GetUserByIdQueryHandler(QueryHandler[GetUserByIdQuery, dict]):
    def __init__(self, repo: UserRepository):
        self.repo = repo

    def _handle(self, query: GetUserByIdQuery) -> dict:
        member = self.repo.get_member(query.tenant_id, query.user_id)
        if member is None:
            raise NotFoundError(f"User with id {query.user_id} not found")
        return member.dict()
