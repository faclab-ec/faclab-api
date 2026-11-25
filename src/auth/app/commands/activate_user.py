from dataclasses import dataclass
from uuid import UUID

from wireup import injectable

from src.auth.app.commands.members import get_user, lock_membership, member_dict
from src.auth.app.repositories import UserRepository
from src.shared.app.audit import AuditAction, AuditTrail
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.plans import PlanLimits, PlanResource
from src.tenancy.app.repositories import MembershipRepository


@dataclass
class ActivateUserCommand(Command):
    tenant_id: UUID
    user_id: int = 0


@injectable(lifetime="scoped")
class ActivateUserCommandHandler(CommandHandler[ActivateUserCommand, dict]):
    """Devuelve al usuario a la empresa (activa su membresía): ocupa un cupo
    del plan (S8.4)"""

    def __init__(
        self,
        repo: UserRepository,
        memberships: MembershipRepository,
        limits: PlanLimits,
        audit: AuditTrail,
    ):
        self.repo = repo
        self.memberships = memberships
        self.limits = limits
        self.audit = audit

    def _handle(self, command: ActivateUserCommand) -> dict:
        membership = lock_membership(
            self.memberships, command.tenant_id, command.user_id
        )
        user = get_user(self.repo, command.user_id)

        if not membership.active:
            self.limits.ensure_room(PlanResource.USERS)
        before = {"active": membership.active}
        membership.activate()
        membership = self.memberships.update(membership)
        self.audit.record(
            AuditAction.USER_ACTIVATED,
            command.user_id,
            before=before,
            after={"active": membership.active},
        )
        return member_dict(user, membership)
