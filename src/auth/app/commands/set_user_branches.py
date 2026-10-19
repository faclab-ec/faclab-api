from dataclasses import dataclass, field
from uuid import UUID

from wireup import injectable

from src.auth.app.commands.members import lock_membership
from src.shared.app.commands import Command, CommandHandler
from src.tenancy.app.repositories import MembershipRepository


@dataclass
class SetUserBranchesCommand(Command):
    tenant_id: UUID
    user_id: int = 0
    branch_ids: list[int] = field(default_factory=list)


@injectable(lifetime="scoped")
class SetUserBranchesCommandHandler(CommandHandler[SetUserBranchesCommand, dict]):
    """Limita al usuario a esas sucursales de la empresa; sin ninguna, puede
    entrar a todas. Rige desde su próximo login o refresh (claim `bids`), como
    un cambio de rol. Una sucursal que no es de la empresa falla su FK
    compuesta: `REFERENCE_NOT_FOUND`."""

    def __init__(self, memberships: MembershipRepository):
        self.memberships = memberships

    def _handle(self, command: SetUserBranchesCommand) -> dict:
        membership = lock_membership(
            self.memberships, command.tenant_id, command.user_id
        )
        self.memberships.set_branches(membership, command.branch_ids)
        return {
            "user_id": command.user_id,
            "branch_ids": self.memberships.branch_ids(membership.require_id()),
        }
