from dataclasses import dataclass
from uuid import UUID

from wireup import injectable

from src.auth.app.commands.members import member_dict
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
from src.tenancy.app.repositories import MembershipRepository
from src.tenancy.domain.entities import Membership


@dataclass
class CreateUserCommand(Command):
    tenant_id: UUID
    username: str = ""
    email: str = ""
    password: str = ""
    role: int = Role.VIEWER.value
    is_active: bool = True
    full_name: str | None = None


@injectable(lifetime="scoped")
class CreateUserCommandHandler(CommandHandler[CreateUserCommand, dict]):
    """Crea el usuario (identidad global) y su membresía en la empresa. El
    usuario y el email son únicos en toda la plataforma."""

    def __init__(
        self,
        repo: UserRepository,
        memberships: MembershipRepository,
        hasher: PasswordHasher,
        event_publisher: EventPublisher,
    ):
        self.repo = repo
        self.memberships = memberships
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
        )
        user.rename(command.full_name)
        user = self.repo.create(user)
        membership = self.memberships.create(
            Membership(
                tenant_id=command.tenant_id,
                user_id=user.require_id(),
                role=Role(command.role),
                active=command.is_active,
            )
        )

        self.event_publisher.publish(
            UserCreated(
                aggregate_id=user.require_id(),
                user_id=user.require_id(),
                username=user.username,
                email=user.email,
                tenant_id=str(command.tenant_id),
                role=membership.role.value,
            )
        )
        return member_dict(user, membership)
