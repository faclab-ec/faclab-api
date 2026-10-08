from sqlalchemy.orm import Session
from wireup import injectable

from src.inventory.serial.app.repositories import SerialNumberRepository
from src.inventory.serial.domain.entities import SerialNumber
from src.inventory.serial.domain.exceptions import SerialNumberAlreadyExistsError
from src.inventory.serial.infra.mappers import SerialNumberMapper
from src.inventory.serial.infra.models import SerialNumberModel
from src.shared.infra.repositories import SqlAlchemyRepository


@injectable(lifetime="scoped", as_type=SerialNumberRepository)
class SqlAlchemySerialNumberRepository(
    SqlAlchemyRepository[SerialNumber], SerialNumberRepository
):
    __model__ = SerialNumberModel
    __unique_errors__ = {
        "serial_numbers_serial_number_key": SerialNumberAlreadyExistsError,
    }

    def __init__(self, session: Session, mapper: SerialNumberMapper):
        super().__init__(session, mapper)

    def find_by_serial(self, serial_number: str) -> SerialNumber | None:
        return self.first(serial_number=serial_number)
