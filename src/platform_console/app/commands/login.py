from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NoReturn

from wireup import injectable

from src.auth.app.commands.login import is_locked
from src.auth.app.repositories import LoginFailureRepository, UserRepository
from src.auth.app.services.password_hasher import PasswordHasher
from src.auth.app.services.token_service import PlatformToken, TokenService
from src.auth.domain.entities import LoginFailure, LoginLockoutPolicy
from src.auth.domain.exceptions import (
    LoginFailedError,
    LoginLockedError,
    PasswordChangeRequiredError,
)
from src.platform_console.app.repositories import PlatformOperatorRepository
from src.shared.app.commands import Command, CommandHandler


@dataclass
class PlatformLoginCommand(Command):
    username: str = ""
    password: str = ""
    ip_address: str | None = None


@dataclass(frozen=True)
class PlatformLoginResult:
    token: PlatformToken
    username: str
    display_name: str


@injectable(lifetime="scoped")
class PlatformLoginCommandHandler(
    CommandHandler[PlatformLoginCommand, PlatformLoginResult]
):
    """Logs a platform operator in (S8.5). Same lockout and failures as the
    companies' login; a user who is not an active operator fails like a wrong
    password, so the answer says nothing about who is an operator"""

    def __init__(
        self,
        users: UserRepository,
        operators: PlatformOperatorRepository,
        failures: LoginFailureRepository,
        lockout: LoginLockoutPolicy,
        hasher: PasswordHasher,
        token_service: TokenService,
    ):
        self.users = users
        self.operators = operators
        self.failures = failures
        self.lockout = lockout
        self.hasher = hasher
        self.token_service = token_service

    def _handle(self, command: PlatformLoginCommand) -> PlatformLoginResult:
        now = datetime.now()
        if is_locked(self.failures, self.lockout, now, username=command.username) or (
            command.ip_address is not None
            and is_locked(
                self.failures, self.lockout, now, ip_address=command.ip_address
            )
        ):
            raise LoginLockedError()

        user = self.users.get_by_username(command.username)
        if user is None:
            self.hasher.verify_dummy(command.password)
            self._fail(command, now)
        valid = self.hasher.verify(command.password, user.password_hash)
        operator = self.operators.get_by_user_id(user.require_id())
        if (
            not valid
            or not user.is_active
            or operator is None
            or not operator.is_active
        ):
            self._fail(command, now)
        if user.must_change_password:
            # A temporary password (an admin's reset) never opens the console:
            # the operator changes it first in a company (S9.3)
            raise PasswordChangeRequiredError(
                "change the temporary password before entering the console"
            )

        self.failures.clear_for_username(command.username)
        user.record_login(datetime.now(UTC))
        user = self.users.update(user)
        return PlatformLoginResult(
            token=self.token_service.issue_platform_access(user),
            username=user.username,
            display_name=user.full_name or user.username,
        )

    def _fail(self, command: PlatformLoginCommand, now: datetime) -> NoReturn:
        self.failures.add(
            LoginFailure(
                username=command.username,
                ip_address=command.ip_address,
                attempted_at=now,
            )
        )
        self.failures.purge_before(now - self.lockout.retention)
        raise LoginFailedError()
