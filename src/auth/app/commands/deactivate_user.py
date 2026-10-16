from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from wireup import injectable

from src.auth.app.commands.last_admin import ensure_not_last_admin
from src.auth.app.commands.members import get_user, lock_membership, member_dict
from src.auth.app.repositories import AuthSessionRepository, UserRepository
from src.shared.app.commands import Command, CommandHandler
from src.tenancy.app.repositories import MembershipRepository


@dataclass
class DeactivateUserCommand(Command):
    tenant_id: UUID
    user_id: int = 0


@injectable(lifetime="scoped")
class DeactivateUserCommandHandler(CommandHandler[DeactivateUserCommand, dict]):
    """Quita al usuario de la empresa (desactiva su membresía); sus otras
    empresas no cambian"""

    def __init__(
        self,
        repo: UserRepository,
        session_repo: AuthSessionRepository,
        memberships: MembershipRepository,
    ):
        self.repo = repo
        self.session_repo = session_repo
        self.memberships = memberships

    def _handle(self, command: DeactivateUserCommand) -> dict:
        membership = lock_membership(
            self.memberships, command.tenant_id, command.user_id
        )
        user = get_user(self.repo, command.user_id)

        ensure_not_last_admin(user, membership, self.memberships)
        membership.deactivate()
        membership = self.memberships.update(membership)
        # Its refresh tokens in this tenant stop working now, not when they expire
        self.session_repo.revoke_all_for_user(
            user.require_id(), datetime.now(), tenant_id=command.tenant_id
        )
        return member_dict(user, membership)
