from dataclasses import dataclass

from wireup import injectable

from src.pos.shift.app.repositories import ShiftRepository
from src.pos.shift.domain.specifications import ShiftsByStatus
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.specifications import Specification, all_of


@dataclass
class GetActiveShiftQuery(Query):
    """Query para obtener el turno activo"""

    pass


@injectable(lifetime="scoped")
class GetActiveShiftQueryHandler(QueryHandler[GetActiveShiftQuery, dict | None]):
    """Handler para obtener el turno activo"""

    def __init__(self, repo: ShiftRepository):
        self.repo = repo

    def _handle(self, query: GetActiveShiftQuery) -> dict | None:
        shift = self.repo.first(status="OPEN")
        if shift is None:
            return None
        return shift.dict()


@dataclass
class GetShiftByIdQuery(Query):
    """Query para obtener un turno por ID"""

    shift_id: int


@injectable(lifetime="scoped")
class GetShiftByIdQueryHandler(QueryHandler[GetShiftByIdQuery, dict]):
    """Handler para obtener un turno por ID"""

    def __init__(self, repo: ShiftRepository):
        self.repo = repo

    def _handle(self, query: GetShiftByIdQuery) -> dict:
        shift = self.repo.get_by_id(query.shift_id)
        if shift is None:
            raise NotFoundError(f"Shift with id {query.shift_id} not found")
        return shift.dict()


@dataclass
class GetAllShiftsQuery(Query):
    """Query para obtener todos los turnos"""

    status: str | None = None
    limit: int | None = None
    offset: int | None = None


@injectable(lifetime="scoped")
class GetAllShiftsQueryHandler(QueryHandler[GetAllShiftsQuery, dict]):
    """Handler para obtener todos los turnos"""

    def __init__(self, repo: ShiftRepository):
        self.repo = repo

    def _handle(self, query: GetAllShiftsQuery) -> dict:
        specs: list[Specification] = []
        if query.status is not None:
            specs.append(ShiftsByStatus(query.status))
        # Newest first: this is the shift history
        return self.repo.paginate_by_spec(
            all_of(specs),
            limit=query.limit,
            offset=query.offset,
            order_by="id",
            desc_order=True,
        )
