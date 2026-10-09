from dataclasses import dataclass
from datetime import datetime

from wireup import injectable

from src.auth.app.commands.last_admin import ensure_not_last_admin
from src.auth.app.repositories import AuthSessionRepository, UserRepository
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class DeactivateUserCommand(Command):
    user_id: int = 0


@injectable(lifetime="scoped")
class DeactivateUserCommandHandler(CommandHandler[DeactivateUserCommand, dict]):
    def __init__(self, repo: UserRepository, session_repo: AuthSessionRepository):
        self.repo = repo
        self.session_repo = session_repo

    def _handle(self, command: DeactivateUserCommand) -> dict:
        user = self.repo.get_by_id(command.user_id)
        if user is None:
            raise NotFoundError(f"User with id {command.user_id} not found")

        ensure_not_last_admin(user, self.repo)
        user.deactivate()
        user = self.repo.update(user)
        # Its refresh tokens stop working now, not when they expire
        self.session_repo.revoke_all_for_user(user.require_id(), datetime.now())
        return user.dict()
