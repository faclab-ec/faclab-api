from uuid import UUID

from src.auth.app.repositories import UserRepository
from src.auth.app.types import TenantMember
from src.auth.domain.entities import User
from src.shared.domain.exceptions import NotFoundError
from src.tenancy.app.repositories import MembershipRepository
from src.tenancy.domain.entities import Membership


def lock_membership(
    memberships: MembershipRepository, tenant_id: UUID, user_id: int
) -> Membership:
    """La membresía del usuario en la empresa, bloqueada hasta el fin de la
    transacción; un usuario de otra empresa no existe para esta"""
    membership = memberships.get_for(tenant_id, user_id, for_update=True)
    if membership is None:
        raise NotFoundError(f"User with id {user_id} not found")
    return membership


def get_user(users: UserRepository, user_id: int) -> User:
    user = users.get_by_id(user_id)
    if user is None:
        raise NotFoundError(f"User with id {user_id} not found")
    return user


def member_dict(user: User, membership: Membership) -> dict:
    return TenantMember(user=user, membership=membership).dict()
