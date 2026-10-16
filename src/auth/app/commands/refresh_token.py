import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from wireup import injectable

from src.auth.app.commands.sessions import OpenedSession
from src.auth.app.repositories import AuthSessionRepository, UserRepository
from src.auth.app.services.token_service import TokenService
from src.auth.domain.exceptions import InvalidTokenError, TokenReusedError
from src.shared.app.commands import Command, CommandHandler
from src.tenancy.app.repositories import MembershipRepository


@dataclass
class RefreshTokenCommand(Command):
    refresh_token: str = ""


@injectable(lifetime="scoped")
class RefreshTokenCommandHandler(CommandHandler[RefreshTokenCommand, OpenedSession]):
    """Rota el refresh token mientras la sesión siga activa, y la extiende.

    Un refresh token ya rotado revoca la sesión (`TOKEN_REUSED`), salvo el
    inmediatamente anterior dentro de la gracia: ese recibe el par actual sin
    rotar otra vez, así que las dos pestañas terminan con el mismo token.

    La sesión sigue en su empresa con el rol actual de la membresía; si la
    membresía o la empresa ya no están activas, termina.
    """

    def __init__(
        self,
        repo: UserRepository,
        session_repo: AuthSessionRepository,
        memberships: MembershipRepository,
        token_service: TokenService,
    ):
        self.repo = repo
        self.session_repo = session_repo
        self.memberships = memberships
        self.token_service = token_service

    def _handle(self, command: RefreshTokenCommand) -> OpenedSession:
        claims = self.token_service.decode_refresh(command.refresh_token)
        if claims.sid is None or claims.jti is None:
            raise InvalidTokenError("refresh token has no session; log in again")

        now = datetime.now()
        # Locked so concurrent refreshes of the session see each other's rotation
        session = self.session_repo.first_for_update(id=claims.sid)
        if session is None or session.user_id != claims.sub:
            raise InvalidTokenError("session not found")
        if not session.is_active(now):
            raise InvalidTokenError("session ended")
        jti = session.refresh_jti
        if jti is None:
            # Opened before refresh tokens rotated
            raise InvalidTokenError("session ended")

        grace = timedelta(seconds=self.token_service.refresh_reuse_grace_seconds)
        if claims.jti == jti:
            jti = uuid.uuid4().hex
            session.rotate(jti, now)
        elif not session.accepts_previous(claims.jti, now, grace):
            session.revoke(now)
            self.session_repo.update(session)
            raise TokenReusedError()

        user = self.repo.get_by_id(claims.sub)
        if user is None or not user.is_active:
            raise InvalidTokenError("user no longer valid")
        access = self.memberships.active_access(user.require_id(), session.tenant_id)
        if access is None:
            raise InvalidTokenError("session ended")

        session.extend(now + timedelta(seconds=self.token_service.refresh_ttl_seconds))
        session = self.session_repo.update(session)
        pair = self.token_service.issue_pair(
            user, access.membership, session.require_id(), jti
        )
        return OpenedSession(pair=pair, tenant=access.tenant)
