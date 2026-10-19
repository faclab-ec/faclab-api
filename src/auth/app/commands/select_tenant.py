from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from wireup import injectable

from src.auth.app.commands.sessions import OpenedSession, branch_limit, open_session
from src.auth.app.repositories import AuthSessionRepository, UserRepository
from src.auth.app.services.token_service import TokenService
from src.auth.domain.exceptions import InvalidTokenError, TenantAccessDeniedError
from src.shared.app.commands import Command, CommandHandler
from src.tenancy.app.repositories import MembershipRepository


@dataclass
class SelectTenantCommand(Command):
    tenant_id: UUID
    # The selection token of the login, or the access token of the session
    # that switches to another tenant
    token: str = ""


@injectable(lifetime="scoped")
class SelectTenantCommandHandler(CommandHandler[SelectTenantCommand, OpenedSession]):
    """Abre una sesión en la empresa elegida.

    Con el token de selección del login, después de validar la contraseña.
    Con un access token, para cambiar de empresa: la sesión actual tiene que
    seguir activa (un logout no se deshace con un access token vigente) y se
    cierra, porque su cookie queda reemplazada por la de la nueva.
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

    def _handle(self, command: SelectTenantCommand) -> OpenedSession:
        claims = self.token_service.decode_selection(command.token)
        now = datetime.now()

        current = None
        if claims.typ == "access":
            if claims.sid is None:
                raise InvalidTokenError("invalid token")
            current = self.session_repo.first_for_update(id=claims.sid)
            if (
                current is None
                or current.user_id != claims.sub
                or not current.is_active(now)
            ):
                raise InvalidTokenError("session ended")

        user = self.repo.get_by_id(claims.sub)
        if user is None or not user.is_active:
            raise InvalidTokenError("user no longer valid")
        access = self.memberships.active_access(user.require_id(), command.tenant_id)
        if access is None:
            raise TenantAccessDeniedError()

        if current is not None:
            current.revoke(now)
            self.session_repo.update(current)
        return open_session(
            self.session_repo,
            self.token_service,
            user,
            access.membership,
            access.tenant,
            now,
            branch_ids=branch_limit(self.memberships, access.membership),
        )
