from dataclasses import dataclass
from datetime import datetime

from wireup import injectable

from src.inventory.movement.app.repositories import MovementRepository
from src.inventory.movement.domain.specifications import (
    MovementsByProduct,
    MovementsByType,
    MovementsInDateRange,
)
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.specifications import Specification, all_of


@dataclass
class GetAllMovementsQuery(Query):
    """Query para obtener todos los movimientos con filtros opcionales"""

    product_id: int | None = None
    type: str | None = None
    from_date: datetime | None = None
    to_date: datetime | None = None
    limit: int | None = None
    offset: int | None = None


@injectable(lifetime="scoped")
class GetAllMovementsQueryHandler(QueryHandler[GetAllMovementsQuery, dict]):
    def __init__(self, repo: MovementRepository):
        self.repo = repo

    def _handle(self, query: GetAllMovementsQuery) -> dict:
        specs: list[Specification] = []
        if query.product_id is not None:
            specs.append(MovementsByProduct(query.product_id))
        if query.type is not None:
            specs.append(MovementsByType(query.type))
        if query.from_date is not None or query.to_date is not None:
            specs.append(MovementsInDateRange(query.from_date, query.to_date))
        return self.repo.paginate_by_spec(
            all_of(specs), limit=query.limit, offset=query.offset
        )


@dataclass
class GetMovementByIdQuery(Query):
    """Query para obtener un movimiento por su ID"""

    id: int = 0


@injectable(lifetime="scoped")
class GetMovementByIdQueryHandler(QueryHandler[GetMovementByIdQuery, dict]):
    def __init__(self, repo: MovementRepository):
        self.repo = repo

    def _handle(self, query: GetMovementByIdQuery) -> dict:
        movement = self.repo.get_by_id(query.id)
        if movement is None:
            raise NotFoundError(f"Movement with id {query.id} not found")
        return movement.dict()
