from dataclasses import dataclass

from wireup import injectable

from src.auth.app.repositories import UserRepository
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class ActivateUserCommand(Command):
    user_id: int = 0


@injectable(lifetime="scoped")
class ActivateUserCommandHandler(CommandHandler[ActivateUserCommand, dict]):
    def __init__(self, repo: UserRepository):
        self.repo = repo

    def _handle(self, command: ActivateUserCommand) -> dict:
        user = self.repo.get_by_id(command.user_id)
        if user is None:
            raise NotFoundError(f"User with id {command.user_id} not found")

        user.activate()
        user = self.repo.update(user)
        return user.dict()
