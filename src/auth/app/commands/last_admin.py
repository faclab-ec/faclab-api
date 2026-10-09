from src.auth.app.repositories import UserRepository
from src.auth.domain.entities import Role, User
from src.auth.domain.exceptions import LastAdminError


def ensure_not_last_admin(user: User, repo: UserRepository) -> None:
    """Falla si `user` es el único admin activo: sin él nadie podría gestionar
    usuarios"""
    if user.role != Role.ADMIN or not user.is_active:
        return
    if repo.count_by(role=int(Role.ADMIN), is_active=True) <= 1:
        raise LastAdminError(user.require_id())
