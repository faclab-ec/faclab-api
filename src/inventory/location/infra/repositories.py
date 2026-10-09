from sqlalchemy.orm import Session
from wireup import injectable

from src.inventory.location.app.repositories import LocationRepository
from src.inventory.location.domain.entities import Location
from src.inventory.location.domain.exceptions import LocationCodeAlreadyExistsError
from src.inventory.location.infra.mappers import LocationMapper
from src.inventory.location.infra.models import LocationModel
from src.shared.infra.repositories import SqlAlchemyRepository


@injectable(lifetime="scoped", as_type=LocationRepository)
class SqlAlchemyLocationRepository(SqlAlchemyRepository[Location], LocationRepository):
    __model__ = LocationModel
    __unique_errors__ = {
        "uq_location_warehouse_code": LocationCodeAlreadyExistsError,
    }

    def __init__(self, session: Session, mapper: LocationMapper):
        super().__init__(session, mapper)
