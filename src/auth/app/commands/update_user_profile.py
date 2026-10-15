from dataclasses import dataclass

from wireup import injectable

from src.auth.app.repositories import UserRepository
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class UpdateUserProfileCommand(Command):
    user_id: int = 0
    full_name: str | None = None


@injectable(lifetime="scoped")
class UpdateUserProfileCommandHandler(CommandHandler[UpdateUserProfileCommand, dict]):
    """Cambia el nombre que se guarda como autor. Los access tokens vigentes
    llevan el nombre anterior hasta el próximo refresh."""

    def __init__(self, repo: UserRepository):
        self.repo = repo

    def _handle(self, command: UpdateUserProfileCommand) -> dict:
        user = self.repo.get_by_id(command.user_id)
        if user is None:
            raise NotFoundError(f"User with id {command.user_id} not found")

        user.rename(command.full_name)
        user = self.repo.update(user)
        return user.dict()
