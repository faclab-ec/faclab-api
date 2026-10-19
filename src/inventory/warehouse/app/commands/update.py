from dataclasses import dataclass

from wireup import injectable

from src.inventory.warehouse.app.repositories import WarehouseRepository
from src.inventory.warehouse.domain.entities import Warehouse
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class UpdateWarehouseCommand(Command):
    """The branch of a warehouse is fixed when it is created"""

    warehouse_id: int
    name: str
    code: str
    address: str | None = None
    city: str | None = None
    country: str | None = None
    is_active: bool = True
    is_default: bool = False
    manager: str | None = None
    phone: str | None = None
    email: str | None = None


@injectable(lifetime="scoped")
class UpdateWarehouseCommandHandler(CommandHandler[UpdateWarehouseCommand, dict]):
    def __init__(self, repo: WarehouseRepository):
        self.repo = repo

    def _handle(self, command: UpdateWarehouseCommand) -> dict:
        warehouse = self.repo.get_by_id(command.warehouse_id)
        if warehouse is None:
            raise NotFoundError(f"Warehouse {command.warehouse_id} not found")
        warehouse = Warehouse(
            id=command.warehouse_id,
            branch_id=warehouse.branch_id,
            name=command.name,
            code=command.code,
            address=command.address,
            city=command.city,
            country=command.country,
            is_active=command.is_active,
            is_default=command.is_default,
            manager=command.manager,
            phone=command.phone,
            email=command.email,
        )
        warehouse = self.repo.update(warehouse)
        return warehouse.dict()
