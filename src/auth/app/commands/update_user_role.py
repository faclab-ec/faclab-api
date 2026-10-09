from dataclasses import dataclass

from wireup import injectable

from src.auth.app.commands.last_admin import ensure_not_last_admin
from src.auth.app.repositories import UserRepository
from src.auth.domain.entities import Role
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class UpdateUserRoleCommand(Command):
    user_id: int = 0
    role: int = Role.VIEWER.value


@injectable(lifetime="scoped")
class UpdateUserRoleCommandHandler(CommandHandler[UpdateUserRoleCommand, dict]):
    def __init__(self, repo: UserRepository):
        self.repo = repo

    def _handle(self, command: UpdateUserRoleCommand) -> dict:
        user = self.repo.get_by_id(command.user_id)
        if user is None:
            raise NotFoundError(f"User with id {command.user_id} not found")

        role = Role(command.role)
        if role != Role.ADMIN:
            ensure_not_last_admin(user, self.repo)
        user.change_role(role)
        user = self.repo.update(user)
        return user.dict()
