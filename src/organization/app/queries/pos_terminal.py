from dataclasses import dataclass

from wireup import injectable

from src.organization.app.repositories import BranchRepository, PosTerminalRepository
from src.organization.domain.exceptions import BranchInactiveError
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class GetAllPosTerminalsQuery(Query):
    branch_id: int | None = None
    is_active: bool | None = None
    limit: int | None = None
    offset: int | None = None


@injectable(lifetime="scoped")
class GetAllPosTerminalsQueryHandler(QueryHandler[GetAllPosTerminalsQuery, dict]):
    def __init__(self, repo: PosTerminalRepository):
        self.repo = repo

    def _handle(self, query: GetAllPosTerminalsQuery) -> dict:
        filters: dict = {}
        if query.branch_id is not None:
            filters["branch_id"] = query.branch_id
        if query.is_active is not None:
            filters["is_active"] = query.is_active
        return self.repo.paginate(limit=query.limit, offset=query.offset, **filters)


@dataclass
class GetPosTerminalByIdQuery(Query):
    terminal_id: int


@injectable(lifetime="scoped")
class GetPosTerminalByIdQueryHandler(QueryHandler[GetPosTerminalByIdQuery, dict]):
    def __init__(self, repo: PosTerminalRepository):
        self.repo = repo

    def _handle(self, query: GetPosTerminalByIdQuery) -> dict:
        terminal = self.repo.get_by_id(query.terminal_id)
        if terminal is None:
            raise NotFoundError(f"POS terminal {query.terminal_id} not found")
        return terminal.dict()


@dataclass
class GetBranchTerminalsQuery(Query):
    """The active terminals of the request's branch (`X-Branch-Id`)"""

    branch_id: int


@injectable(lifetime="scoped")
class GetBranchTerminalsQueryHandler(QueryHandler[GetBranchTerminalsQuery, list[dict]]):
    def __init__(self, repo: PosTerminalRepository, branches: BranchRepository):
        self.repo = repo
        self.branches = branches

    def _handle(self, query: GetBranchTerminalsQuery) -> list[dict]:
        branch = self.branches.get_by_id(query.branch_id)
        if branch is None:
            raise NotFoundError(f"Branch {query.branch_id} not found")
        if not branch.is_active:
            raise BranchInactiveError(query.branch_id)
        terminals = self.repo.filter_by(branch_id=query.branch_id, is_active=True)
        return [t.dict() for t in sorted(terminals, key=lambda t: t.code)]
