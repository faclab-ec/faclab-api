from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from wireup import injectable

from src.auth.app.repositories import AuthSessionRepository, UserRepository
from src.auth.app.services.password_hasher import PasswordHasher
from src.auth.app.services.token_service import TokenPair, TokenService
from src.auth.domain.entities import AuthSession
from src.auth.domain.events import UserLoggedIn
from src.auth.domain.exceptions import InvalidCredentialsError
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher


@dataclass
class LoginCommand(Command):
    username: str = ""
    password: str = ""


@injectable(lifetime="scoped")
class LoginCommandHandler(CommandHandler[LoginCommand, TokenPair]):
    def __init__(
        self,
        repo: UserRepository,
        session_repo: AuthSessionRepository,
        hasher: PasswordHasher,
        token_service: TokenService,
        event_publisher: EventPublisher,
    ):
        self.repo = repo
        self.session_repo = session_repo
        self.hasher = hasher
        self.token_service = token_service
        self.event_publisher = event_publisher

    def _handle(self, command: LoginCommand) -> TokenPair:
        user = self.repo.get_by_username(command.username)
        if user is None or not user.is_active:
            raise InvalidCredentialsError("invalid username or password")
        if not self.hasher.verify(command.password, user.password_hash):
            raise InvalidCredentialsError("invalid username or password")

        user.record_login(datetime.now(UTC))
        user = self.repo.update(user)

        self.event_publisher.publish(
            UserLoggedIn(
                aggregate_id=user.require_id(),
                user_id=user.require_id(),
                username=user.username,
            )
        )

        session = self.session_repo.create(
            AuthSession(
                user_id=user.require_id(),
                expires_at=datetime.now()
                + timedelta(seconds=self.token_service.refresh_ttl_seconds),
            )
        )
        return self.token_service.issue_pair(user, session.require_id())
