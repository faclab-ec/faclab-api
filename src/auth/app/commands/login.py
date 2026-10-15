import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn

from wireup import injectable

from src.auth.app.repositories import (
    AuthSessionRepository,
    LoginFailureRepository,
    UserRepository,
)
from src.auth.app.services.password_hasher import PasswordHasher
from src.auth.app.services.token_service import TokenPair, TokenService
from src.auth.domain.entities import AuthSession, LoginFailure, LoginLockoutPolicy
from src.auth.domain.events import UserLoggedIn
from src.auth.domain.exceptions import LoginFailedError, LoginLockedError
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher


@dataclass
class LoginCommand(Command):
    username: str = ""
    password: str = ""
    ip_address: str | None = None


@injectable(lifetime="scoped")
class LoginCommandHandler(CommandHandler[LoginCommand, TokenPair]):
    def __init__(
        self,
        repo: UserRepository,
        session_repo: AuthSessionRepository,
        failure_repo: LoginFailureRepository,
        lockout: LoginLockoutPolicy,
        hasher: PasswordHasher,
        token_service: TokenService,
        event_publisher: EventPublisher,
    ):
        self.repo = repo
        self.session_repo = session_repo
        self.failure_repo = failure_repo
        self.lockout = lockout
        self.hasher = hasher
        self.token_service = token_service
        self.event_publisher = event_publisher

    def _handle(self, command: LoginCommand) -> TokenPair:
        now = datetime.now()
        # While locked nothing is checked or recorded, so the lock ends on time
        # even if the attempts keep coming
        if self._is_locked(now, username=command.username) or (
            command.ip_address is not None
            and self._is_locked(now, ip_address=command.ip_address)
        ):
            raise LoginLockedError()

        user = self.repo.get_by_username(command.username)
        if user is None:
            self.hasher.verify_dummy(command.password)
            self._fail(command, now)
        valid = self.hasher.verify(command.password, user.password_hash)
        if not valid or not user.is_active:
            self._fail(command, now)

        self.failure_repo.clear_for_username(command.username)
        user.record_login(datetime.now(UTC))
        user = self.repo.update(user)

        self.event_publisher.publish(
            UserLoggedIn(
                aggregate_id=user.require_id(),
                user_id=user.require_id(),
                username=user.username,
            )
        )

        refresh_jti = uuid.uuid4().hex
        session = self.session_repo.create(
            AuthSession(
                user_id=user.require_id(),
                expires_at=now
                + timedelta(seconds=self.token_service.refresh_ttl_seconds),
                refresh_jti=refresh_jti,
                refreshed_at=now,
            )
        )
        return self.token_service.issue_pair(user, session.require_id(), refresh_jti)

    def _is_locked(
        self,
        now: datetime,
        *,
        username: str | None = None,
        ip_address: str | None = None,
    ) -> bool:
        last = self.failure_repo.last_failure_at(
            username=username, ip_address=ip_address
        )
        if last is None or now >= last + self.lockout.lockout:
            return False
        limit = (
            self.lockout.max_failures_per_user
            if username is not None
            else self.lockout.max_failures_per_ip
        )
        failures = self.failure_repo.count_since(
            last - self.lockout.window, username=username, ip_address=ip_address
        )
        return failures >= limit

    def _fail(self, command: LoginCommand, now: datetime) -> NoReturn:
        self.failure_repo.add(
            LoginFailure(
                username=command.username,
                ip_address=command.ip_address,
                attempted_at=now,
            )
        )
        self.failure_repo.purge_before(now - self.lockout.retention)
        raise LoginFailedError()
