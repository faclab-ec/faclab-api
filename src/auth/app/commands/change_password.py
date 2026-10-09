from dataclasses import dataclass
from datetime import datetime

from wireup import injectable

from src.auth.app.repositories import AuthSessionRepository, UserRepository
from src.auth.app.services.password_hasher import PasswordHasher
from src.auth.domain.events import UserPasswordChanged
from src.auth.domain.exceptions import InvalidCredentialsError
from src.auth.domain.value_objects import PlainPassword
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError


@dataclass
class ChangePasswordCommand(Command):
    user_id: int = 0
    current_password: str = ""
    new_password: str = ""
    # The session making the change stays open; every other one is closed
    keep_session_id: int | None = None


@injectable(lifetime="scoped")
class ChangePasswordCommandHandler(CommandHandler[ChangePasswordCommand, None]):
    def __init__(
        self,
        repo: UserRepository,
        session_repo: AuthSessionRepository,
        hasher: PasswordHasher,
        event_publisher: EventPublisher,
    ):
        self.repo = repo
        self.session_repo = session_repo
        self.hasher = hasher
        self.event_publisher = event_publisher

    def _handle(self, command: ChangePasswordCommand) -> None:
        user = self.repo.get_by_id(command.user_id)
        if user is None:
            raise NotFoundError(f"User with id {command.user_id} not found")

        PlainPassword(command.new_password)

        if not self.hasher.verify(command.current_password, user.password_hash):
            raise InvalidCredentialsError("current password is incorrect")

        new_hash = self.hasher.hash(command.new_password)
        user.change_password(new_hash)
        self.repo.update(user)
        self.session_repo.revoke_all_for_user(
            user.require_id(), datetime.now(), command.keep_session_id
        )

        self.event_publisher.publish(
            UserPasswordChanged(
                aggregate_id=user.require_id(),
                user_id=user.require_id(),
                username=user.username,
            )
        )
