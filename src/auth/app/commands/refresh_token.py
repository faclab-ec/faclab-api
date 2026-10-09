from dataclasses import dataclass
from datetime import datetime, timedelta

from wireup import injectable

from src.auth.app.repositories import AuthSessionRepository, UserRepository
from src.auth.app.services.token_service import TokenPair, TokenService
from src.auth.domain.exceptions import InvalidTokenError
from src.shared.app.commands import Command, CommandHandler


@dataclass
class RefreshTokenCommand(Command):
    refresh_token: str = ""


@injectable(lifetime="scoped")
class RefreshTokenCommandHandler(CommandHandler[RefreshTokenCommand, TokenPair]):
    """Emite tokens nuevos mientras la sesión siga activa, y la extiende"""

    def __init__(
        self,
        repo: UserRepository,
        session_repo: AuthSessionRepository,
        token_service: TokenService,
    ):
        self.repo = repo
        self.session_repo = session_repo
        self.token_service = token_service

    def _handle(self, command: RefreshTokenCommand) -> TokenPair:
        claims = self.token_service.decode_refresh(command.refresh_token)
        if claims.sid is None:
            raise InvalidTokenError("refresh token has no session; log in again")

        now = datetime.now()
        session = self.session_repo.get_by_id(claims.sid)
        if session is None or session.user_id != claims.sub:
            raise InvalidTokenError("session not found")
        if not session.is_active(now):
            raise InvalidTokenError("session ended")

        user = self.repo.get_by_id(claims.sub)
        if user is None or not user.is_active:
            raise InvalidTokenError("user no longer valid")

        session.extend(now + timedelta(seconds=self.token_service.refresh_ttl_seconds))
        self.session_repo.update(session)
        return self.token_service.issue_pair(user, session.require_id())
