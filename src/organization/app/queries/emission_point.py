from dataclasses import dataclass

from wireup import injectable

from src.organization.app.repositories import EmissionPointRepository
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class GetAllEmissionPointsQuery(Query):
    branch_id: int | None = None
    is_active: bool | None = None
    limit: int | None = None
    offset: int | None = None


@injectable(lifetime="scoped")
class GetAllEmissionPointsQueryHandler(QueryHandler[GetAllEmissionPointsQuery, dict]):
    def __init__(self, repo: EmissionPointRepository):
        self.repo = repo

    def _handle(self, query: GetAllEmissionPointsQuery) -> dict:
        filters: dict = {}
        if query.branch_id is not None:
            filters["branch_id"] = query.branch_id
        if query.is_active is not None:
            filters["is_active"] = query.is_active
        return self.repo.paginate(limit=query.limit, offset=query.offset, **filters)


@dataclass
class GetEmissionPointByIdQuery(Query):
    emission_point_id: int


@injectable(lifetime="scoped")
class GetEmissionPointByIdQueryHandler(QueryHandler[GetEmissionPointByIdQuery, dict]):
    def __init__(self, repo: EmissionPointRepository):
        self.repo = repo

    def _handle(self, query: GetEmissionPointByIdQuery) -> dict:
        point = self.repo.get_by_id(query.emission_point_id)
        if point is None:
            raise NotFoundError(f"Emission point {query.emission_point_id} not found")
        return point.dict()
