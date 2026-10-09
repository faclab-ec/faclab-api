from dataclasses import dataclass
from datetime import datetime

from wireup import injectable

from src.auth.app.repositories import AuthSessionRepository
from src.auth.app.services.token_service import TokenService
from src.auth.domain.exceptions import InvalidTokenError, TokenExpiredError
from src.shared.app.commands import Command, CommandHandler


@dataclass
class LogoutCommand(Command):
    refresh_token: str = ""


@injectable(lifetime="scoped")
class LogoutCommandHandler(CommandHandler[LogoutCommand, None]):
    """Revoca la sesión del refresh token.

    Un token vencido, inválido o de una sesión ya cerrada no deja nada que
    cerrar, así que logout nunca falla: el cliente borra sus tokens igual.
    """

    def __init__(
        self, session_repo: AuthSessionRepository, token_service: TokenService
    ):
        self.session_repo = session_repo
        self.token_service = token_service

    def _handle(self, command: LogoutCommand) -> None:
        try:
            claims = self.token_service.decode_refresh(command.refresh_token)
        except (InvalidTokenError, TokenExpiredError):
            return
        if claims.sid is None:
            return

        session = self.session_repo.get_by_id(claims.sid)
        if session is None or session.user_id != claims.sub:
            return
        session.revoke(datetime.now())
        self.session_repo.update(session)
