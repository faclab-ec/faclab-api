from sqlalchemy.orm import Session
from wireup import injectable

from src.inventory.movement.app.repositories import MovementRepository
from src.inventory.movement.domain.entities import Movement
from src.inventory.movement.infra.mappers import MovementMapper
from src.inventory.movement.infra.metrics import count_movement
from src.inventory.movement.infra.models import MovementModel
from src.shared.infra.repositories import SqlAlchemyRepository


@injectable(lifetime="scoped", as_type=MovementRepository)
class SqlAlchemyMovementRepository(SqlAlchemyRepository[Movement], MovementRepository):
    __model__ = MovementModel

    def __init__(self, session: Session, mapper: MovementMapper):
        super().__init__(session, mapper)

    def create(self, entity: Movement) -> Movement:
        """Every movement is written here, by a document (TerminalStock) or by
        CreateMovementCommand, so here it is counted (S7.1)"""
        movement = super().create(entity)
        count_movement(self.session, movement)
        return movement
