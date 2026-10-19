from dataclasses import dataclass

from wireup import injectable

from src.pos.shift.app.repositories import ShiftRepository
from src.pos.shift.domain.specifications import (
    ShiftsByStatus,
    ShiftsByTerminal,
    ShiftsInBranches,
)
from src.pos.terminal.app.resolver import TerminalRequest, TerminalResolver
from src.pos.terminal.app.scope import branch_scope, in_scope
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.specifications import Specification, all_of


@dataclass
class GetActiveShiftQuery(Query):
    """Query para obtener el turno activo de la terminal"""

    terminal: TerminalRequest


@injectable(lifetime="scoped")
class GetActiveShiftQueryHandler(QueryHandler[GetActiveShiftQuery, dict | None]):
    """Handler para obtener el turno activo"""

    def __init__(self, repo: ShiftRepository, terminals: TerminalResolver):
        self.repo = repo
        self.terminals = terminals

    def _handle(self, query: GetActiveShiftQuery) -> dict | None:
        terminal = self.terminals.terminal(query.terminal)
        shift = self.repo.first(terminal_id=terminal.id, status="OPEN")
        if shift is None:
            return None
        return shift.dict()


@dataclass
class GetShiftByIdQuery(Query):
    """Query para obtener un turno por ID"""

    shift_id: int
    # The user's branches (None: all); another branch's shift is not found
    branch_ids: frozenset[int] | None = None


@injectable(lifetime="scoped")
class GetShiftByIdQueryHandler(QueryHandler[GetShiftByIdQuery, dict]):
    """Handler para obtener un turno por ID"""

    def __init__(self, repo: ShiftRepository):
        self.repo = repo

    def _handle(self, query: GetShiftByIdQuery) -> dict:
        shift = self.repo.get_by_id(query.shift_id)
        if shift is None or not in_scope(shift.branch_id, query.branch_ids):
            raise NotFoundError(f"Shift with id {query.shift_id} not found")
        return shift.dict()


@dataclass
class GetAllShiftsQuery(Query):
    """Query para obtener todos los turnos"""

    status: str | None = None
    branch_id: int | None = None
    terminal_id: int | None = None
    # The user's branches (None: all)
    branch_ids: frozenset[int] | None = None
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
        if query.terminal_id is not None:
            specs.append(ShiftsByTerminal(query.terminal_id))
        scope = branch_scope(query.branch_id, query.branch_ids)
        if scope is not None:
            specs.append(ShiftsInBranches(scope))
        # Newest first: this is the shift history
        return self.repo.paginate_by_spec(
            all_of(specs),
            limit=query.limit,
            offset=query.offset,
            order_by="id",
            desc_order=True,
        )
