from src.auth.domain.entities import User
from src.auth.domain.exceptions import LastAdminError
from src.tenancy.app.repositories import MembershipRepository
from src.tenancy.domain.entities import Membership


def ensure_not_last_admin(
    user: User, membership: Membership, memberships: MembershipRepository
) -> None:
    """Falla si `user` es el único admin activo de la empresa de `membership`:
    sin él nadie podría gestionar sus usuarios. Bloquea las membresías de los
    admins, así que dos solicitudes que los degradan van una tras otra."""
    if not (membership.is_admin and membership.active and user.is_active):
        return
    if memberships.lock_active_admins(membership.tenant_id) <= 1:
        raise LastAdminError(user.require_id())
