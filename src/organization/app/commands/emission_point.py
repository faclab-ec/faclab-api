from dataclasses import dataclass

from wireup import injectable

from src.organization.app.repositories import EmissionPointRepository
from src.organization.domain.entities import EmissionPoint
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class CreateEmissionPointCommand(Command):
    branch_id: int
    code: str
    name: str | None = None
    is_active: bool = True


@injectable(lifetime="scoped")
class CreateEmissionPointCommandHandler(
    CommandHandler[CreateEmissionPointCommand, dict]
):
    """A branch of another tenant, or none, fails its composite foreign key:
    `REFERENCE_NOT_FOUND`, as for a location's warehouse."""

    def __init__(self, repo: EmissionPointRepository):
        self.repo = repo

    def _handle(self, command: CreateEmissionPointCommand) -> dict:
        point = EmissionPoint(
            branch_id=command.branch_id,
            code=command.code,
            name=command.name,
            is_active=command.is_active,
        )
        point = self.repo.create(point)
        return point.dict()


@dataclass
class UpdateEmissionPointCommand(Command):
    """The branch of an emission point is fixed when it is created"""

    emission_point_id: int
    code: str
    name: str | None = None
    is_active: bool = True


@injectable(lifetime="scoped")
class UpdateEmissionPointCommandHandler(
    CommandHandler[UpdateEmissionPointCommand, dict]
):
    def __init__(self, repo: EmissionPointRepository):
        self.repo = repo

    def _handle(self, command: UpdateEmissionPointCommand) -> dict:
        point = self.repo.get_by_id(command.emission_point_id)
        if point is None:
            raise NotFoundError(f"Emission point {command.emission_point_id} not found")
        point = EmissionPoint(
            id=command.emission_point_id,
            branch_id=point.branch_id,
            code=command.code,
            name=command.name,
            is_active=command.is_active,
        )
        point = self.repo.update(point)
        return point.dict()


@dataclass
class DeleteEmissionPointCommand(Command):
    emission_point_id: int


@injectable(lifetime="scoped")
class DeleteEmissionPointCommandHandler(
    CommandHandler[DeleteEmissionPointCommand, None]
):
    def __init__(self, repo: EmissionPointRepository):
        self.repo = repo

    def _handle(self, command: DeleteEmissionPointCommand) -> None:
        if self.repo.get_by_id(command.emission_point_id) is None:
            raise NotFoundError(f"Emission point {command.emission_point_id} not found")
        self.repo.delete(command.emission_point_id)
