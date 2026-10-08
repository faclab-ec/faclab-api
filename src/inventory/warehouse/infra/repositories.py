from sqlalchemy.orm import Session
from wireup import injectable

from src.inventory.warehouse.app.repositories import WarehouseRepository
from src.inventory.warehouse.domain.entities import Warehouse
from src.inventory.warehouse.domain.exceptions import WarehouseCodeAlreadyExistsError
from src.inventory.warehouse.infra.mappers import WarehouseMapper
from src.inventory.warehouse.infra.models import WarehouseModel
from src.shared.infra.repositories import SqlAlchemyRepository


@injectable(lifetime="scoped", as_type=WarehouseRepository)
class SqlAlchemyWarehouseRepository(
    SqlAlchemyRepository[Warehouse], WarehouseRepository
):
    __model__ = WarehouseModel
    __unique_errors__ = {
        "warehouses_code_key": WarehouseCodeAlreadyExistsError,
    }

    def __init__(self, session: Session, mapper: WarehouseMapper):
        super().__init__(session, mapper)
