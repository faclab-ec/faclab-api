from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from wireup import injectable

from src.auth.app.commands.members import get_user, lock_membership, member_dict
from src.auth.app.repositories import AuthSessionRepository, UserRepository
from src.auth.app.services.password_hasher import PasswordHasher
from src.auth.domain.events import UserPasswordReset
from src.auth.domain.exceptions import UserInOtherTenantsError
from src.auth.domain.value_objects import PlainPassword
from src.shared.app.audit import AuditAction, AuditTrail
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.tenancy.app.repositories import MembershipRepository


@dataclass
class AdminResetPasswordCommand(Command):
    tenant_id: UUID
    user_id: int = 0
    new_password: str = ""
    reset_by_user_id: int = 0


@injectable(lifetime="scoped")
class AdminResetPasswordCommandHandler(CommandHandler[AdminResetPasswordCommand, dict]):
    """Asigna una contraseña temporal a un usuario de la empresa.

    La contraseña sirve en todas las empresas del usuario: si también trabaja
    en otra, el admin de esta no puede cambiarla (podría entrar a la otra).
    """

    def __init__(
        self,
        repo: UserRepository,
        session_repo: AuthSessionRepository,
        memberships: MembershipRepository,
        hasher: PasswordHasher,
        event_publisher: EventPublisher,
        audit: AuditTrail,
    ):
        self.repo = repo
        self.session_repo = session_repo
        self.memberships = memberships
        self.hasher = hasher
        self.event_publisher = event_publisher
        self.audit = audit

    def _handle(self, command: AdminResetPasswordCommand) -> dict:
        membership = lock_membership(
            self.memberships, command.tenant_id, command.user_id
        )
        if self.memberships.has_active_elsewhere(command.user_id, command.tenant_id):
            raise UserInOtherTenantsError(command.user_id)
        user = get_user(self.repo, command.user_id)

        PlainPassword(command.new_password)

        new_hash = self.hasher.hash(command.new_password)
        user.reset_password(new_hash)
        user = self.repo.update(user)
        # Whoever had the old password is logged out
        self.session_repo.revoke_all_for_user(user.require_id(), datetime.now())
        # Only the fact: never the password
        self.audit.record(AuditAction.USER_PASSWORD_RESET, user.require_id())

        self.event_publisher.publish(
            UserPasswordReset(
                aggregate_id=user.require_id(),
                user_id=user.require_id(),
                username=user.username,
                reset_by_user_id=command.reset_by_user_id,
            )
        )
        return member_dict(user, membership)
