from src.pos.shift.app.commands.close_shift import CloseShiftCommandHandler
from src.pos.shift.app.commands.open_shift import OpenShiftCommandHandler
from src.pos.shift.app.queries.get_shifts import (
    GetActiveShiftQueryHandler,
    GetAllShiftsQueryHandler,
    GetShiftByIdQueryHandler,
)
from src.pos.shift.infra.mappers import ShiftMapper
from src.pos.shift.infra.repositories import (
    SqlAlchemyShiftClosingRepository,
    SqlAlchemyShiftRepository,
)
from src.pos.shift.infra.totals import SqlAlchemyShiftTotalsReader

INJECTABLES = [
    ShiftMapper,
    SqlAlchemyShiftRepository,
    SqlAlchemyShiftClosingRepository,
    SqlAlchemyShiftTotalsReader,
    OpenShiftCommandHandler,
    CloseShiftCommandHandler,
    GetActiveShiftQueryHandler,
    GetShiftByIdQueryHandler,
    GetAllShiftsQueryHandler,
]
