from dataclasses import dataclass

from wireup import injectable

from src.organization.app.repositories import BranchRepository
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class GetAllBranchesQuery(Query):
    is_active: bool | None = None
    limit: int | None = None
    offset: int | None = None


@injectable(lifetime="scoped")
class GetAllBranchesQueryHandler(QueryHandler[GetAllBranchesQuery, dict]):
    def __init__(self, repo: BranchRepository):
        self.repo = repo

    def _handle(self, query: GetAllBranchesQuery) -> dict:
        filters = {}
        if query.is_active is not None:
            filters["is_active"] = query.is_active
        return self.repo.paginate(limit=query.limit, offset=query.offset, **filters)


@dataclass
class GetBranchByIdQuery(Query):
    branch_id: int


@injectable(lifetime="scoped")
class GetBranchByIdQueryHandler(QueryHandler[GetBranchByIdQuery, dict]):
    def __init__(self, repo: BranchRepository):
        self.repo = repo

    def _handle(self, query: GetBranchByIdQuery) -> dict:
        branch = self.repo.get_by_id(query.branch_id)
        if branch is None:
            raise NotFoundError(f"Branch {query.branch_id} not found")
        return branch.dict()


@dataclass
class GetAccessibleBranchesQuery(Query):
    """The active branches a user can enter; `branch_ids` None means all"""

    branch_ids: frozenset[int] | None = None


@injectable(lifetime="scoped")
class GetAccessibleBranchesQueryHandler(
    QueryHandler[GetAccessibleBranchesQuery, list[dict]]
):
    def __init__(self, repo: BranchRepository):
        self.repo = repo

    def _handle(self, query: GetAccessibleBranchesQuery) -> list[dict]:
        branches = self.repo.filter_by(is_active=True)
        return [
            branch.dict()
            for branch in sorted(branches, key=lambda b: b.establishment_code)
            if query.branch_ids is None or branch.id in query.branch_ids
        ]
