from dataclasses import dataclass

from wireup import injectable

from src.catalog.uom.app.repositories import UnitOfMeasureRepository
from src.catalog.uom.domain.entities import UnitOfMeasure
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class UpdateUnitOfMeasureCommand(Command):
    uom_id: int
    name: str
    symbol: str
    description: str | None = None
    is_active: bool = True
    decimals: int = 0


@injectable(lifetime="scoped")
class UpdateUnitOfMeasureCommandHandler(
    CommandHandler[UpdateUnitOfMeasureCommand, dict]
):
    def __init__(self, repo: UnitOfMeasureRepository):
        self.repo = repo

    def _handle(self, command: UpdateUnitOfMeasureCommand) -> dict:
        existing = self.repo.get_by_id(command.uom_id)
        if existing is None:
            raise NotFoundError(f"Unit of measure with id {command.uom_id} not found")
        uom = UnitOfMeasure(
            id=command.uom_id,
            name=command.name,
            symbol=command.symbol,
            description=command.description,
            is_active=command.is_active,
            decimals=command.decimals,
        )
        uom = self.repo.update(uom)
        return uom.dict()
