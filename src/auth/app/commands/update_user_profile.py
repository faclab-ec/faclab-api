from dataclasses import dataclass
from uuid import UUID

from wireup import injectable

from src.auth.app.commands.members import get_user, lock_membership, member_dict
from src.auth.app.repositories import UserRepository
from src.auth.domain.exceptions import UserInOtherTenantsError
from src.shared.app.commands import Command, CommandHandler
from src.tenancy.app.repositories import MembershipRepository


@dataclass
class UpdateUserProfileCommand(Command):
    tenant_id: UUID
    user_id: int = 0
    full_name: str | None = None


@injectable(lifetime="scoped")
class UpdateUserProfileCommandHandler(CommandHandler[UpdateUserProfileCommand, dict]):
    """Cambia el nombre que se guarda como autor. Los access tokens vigentes
    llevan el nombre anterior hasta el próximo refresh.

    El nombre es el mismo en todas las empresas: si el usuario también trabaja
    en otra, esta no puede cambiarlo.
    """

    def __init__(self, repo: UserRepository, memberships: MembershipRepository):
        self.repo = repo
        self.memberships = memberships

    def _handle(self, command: UpdateUserProfileCommand) -> dict:
        membership = lock_membership(
            self.memberships, command.tenant_id, command.user_id
        )
        if self.memberships.has_active_elsewhere(command.user_id, command.tenant_id):
            raise UserInOtherTenantsError(command.user_id)
        user = get_user(self.repo, command.user_id)

        user.rename(command.full_name)
        user = self.repo.update(user)
        return member_dict(user, membership)
