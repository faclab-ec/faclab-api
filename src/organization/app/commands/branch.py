from dataclasses import dataclass

from wireup import injectable

from src.organization.app.repositories import BranchRepository
from src.organization.domain.entities import Branch
from src.organization.domain.exceptions import MainBranchDeletionError
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class CreateBranchCommand(Command):
    establishment_code: str
    name: str
    address: str | None = None
    is_active: bool = True


@injectable(lifetime="scoped")
class CreateBranchCommandHandler(CommandHandler[CreateBranchCommand, dict]):
    def __init__(self, repo: BranchRepository):
        self.repo = repo

    def _handle(self, command: CreateBranchCommand) -> dict:
        branch = Branch(
            establishment_code=command.establishment_code,
            name=command.name,
            address=command.address,
            is_active=command.is_active,
        )
        branch = self.repo.create(branch)
        return branch.dict()


@dataclass
class UpdateBranchCommand(Command):
    branch_id: int
    establishment_code: str
    name: str
    address: str | None = None
    is_active: bool = True


@injectable(lifetime="scoped")
class UpdateBranchCommandHandler(CommandHandler[UpdateBranchCommand, dict]):
    def __init__(self, repo: BranchRepository):
        self.repo = repo

    def _handle(self, command: UpdateBranchCommand) -> dict:
        branch = self.repo.get_by_id(command.branch_id)
        if branch is None:
            raise NotFoundError(f"Branch {command.branch_id} not found")
        branch = Branch(
            id=command.branch_id,
            establishment_code=command.establishment_code,
            name=command.name,
            address=command.address,
            is_main=branch.is_main,
            is_active=command.is_active,
        )
        branch = self.repo.update(branch)
        return branch.dict()


@dataclass
class DeleteBranchCommand(Command):
    branch_id: int


@injectable(lifetime="scoped")
class DeleteBranchCommandHandler(CommandHandler[DeleteBranchCommand, None]):
    """A branch with warehouses, emission points, terminals or user accesses
    can't be deleted either: their foreign keys answer `RECORD_IN_USE`."""

    def __init__(self, repo: BranchRepository):
        self.repo = repo

    def _handle(self, command: DeleteBranchCommand) -> None:
        branch = self.repo.get_by_id(command.branch_id)
        if branch is None:
            raise NotFoundError(f"Branch {command.branch_id} not found")
        if branch.is_main:
            raise MainBranchDeletionError()
        self.repo.delete(command.branch_id)
