from sqlalchemy.orm import Session
from wireup import injectable

from src.pos.shift.app.repositories import ShiftRepository
from src.pos.shift.domain.entities import Shift
from src.pos.shift.domain.exceptions import ShiftAlreadyOpenError
from src.pos.shift.infra.mappers import ShiftMapper
from src.pos.shift.infra.models import ShiftModel
from src.shared.infra.repositories import SqlAlchemyRepository


@injectable(lifetime="scoped", as_type=ShiftRepository)
class SqlAlchemyShiftRepository(SqlAlchemyRepository[Shift], ShiftRepository):
    __model__ = ShiftModel
    __unique_errors__ = {
        "uq_pos_shifts_tenant_terminal_open": ShiftAlreadyOpenError,
    }

    def __init__(self, session: Session, mapper: ShiftMapper):
        super().__init__(session, mapper)
