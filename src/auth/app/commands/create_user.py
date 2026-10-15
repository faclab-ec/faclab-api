from dataclasses import dataclass

from wireup import injectable

from src.auth.app.repositories import UserRepository
from src.auth.app.services.password_hasher import PasswordHasher
from src.auth.domain.entities import Role, User
from src.auth.domain.events import UserCreated
from src.auth.domain.exceptions import (
    EmailAlreadyExistsError,
    UsernameAlreadyExistsError,
)
from src.auth.domain.value_objects import PlainPassword
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.value_objects import Email


@dataclass
class CreateUserCommand(Command):
    username: str = ""
    email: str = ""
    password: str = ""
    role: int = Role.VIEWER.value
    is_active: bool = True
    full_name: str | None = None


@injectable(lifetime="scoped")
class CreateUserCommandHandler(CommandHandler[CreateUserCommand, dict]):
    def __init__(
        self,
        repo: UserRepository,
        hasher: PasswordHasher,
        event_publisher: EventPublisher,
    ):
        self.repo = repo
        self.hasher = hasher
        self.event_publisher = event_publisher

    def _handle(self, command: CreateUserCommand) -> dict:
        Email(command.email)
        PlainPassword(command.password)

        if self.repo.get_by_username(command.username) is not None:
            raise UsernameAlreadyExistsError(
                f"username '{command.username}' already exists"
            )
        if self.repo.get_by_email(command.email) is not None:
            raise EmailAlreadyExistsError(f"email '{command.email}' already exists")

        user = User(
            username=command.username,
            email=command.email,
            password_hash=self.hasher.hash(command.password),
            role=Role(command.role),
            is_active=command.is_active,
        )
        user.rename(command.full_name)
        user = self.repo.create(user)

        self.event_publisher.publish(
            UserCreated(
                aggregate_id=user.require_id(),
                user_id=user.require_id(),
                username=user.username,
                email=user.email,
                role=user.role.value,
            )
        )
        return user.dict()
