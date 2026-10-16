from dataclasses import dataclass
from uuid import UUID

from wireup import injectable

from src.auth.app.commands.last_admin import ensure_not_last_admin
from src.auth.app.commands.members import get_user, lock_membership, member_dict
from src.auth.app.repositories import UserRepository
from src.auth.domain.entities import Role
from src.shared.app.commands import Command, CommandHandler
from src.tenancy.app.repositories import MembershipRepository


@dataclass
class UpdateUserRoleCommand(Command):
    tenant_id: UUID
    user_id: int = 0
    role: int = Role.VIEWER.value


@injectable(lifetime="scoped")
class UpdateUserRoleCommandHandler(CommandHandler[UpdateUserRoleCommand, dict]):
    """Cambia el rol del usuario en la empresa (su membresía)"""

    def __init__(self, repo: UserRepository, memberships: MembershipRepository):
        self.repo = repo
        self.memberships = memberships

    def _handle(self, command: UpdateUserRoleCommand) -> dict:
        membership = lock_membership(
            self.memberships, command.tenant_id, command.user_id
        )
        user = get_user(self.repo, command.user_id)

        role = Role(command.role)
        if role != Role.ADMIN:
            ensure_not_last_admin(user, membership, self.memberships)
        membership.change_role(role)
        membership = self.memberships.update(membership)
        return member_dict(user, membership)
