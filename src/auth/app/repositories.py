from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from src.auth.app.types import TenantMember
from src.auth.domain.entities import AuthSession, LoginFailure, Role, User
from src.shared.app.repositories import Repository


class UserRepository(Repository[User]):
    def get_by_username(self, username: str) -> User | None: ...

    def get_by_email(self, email: str) -> User | None: ...

    @abstractmethod
    def get_member(self, tenant_id: UUID, user_id: int) -> TenantMember | None:
        """The user with its membership in the tenant, active or not"""

    @abstractmethod
    def paginate_members(
        self,
        tenant_id: UUID,
        *,
        role: Role | None = None,
        is_active: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict:
        """The tenant's users as `{items, total, limit, offset}`, items being
        `TenantMember.dict()`; `role` and `is_active` filter the membership"""


class AuthSessionRepository(Repository[AuthSession]):
    @abstractmethod
    def first_for_update(self, **kwargs) -> AuthSession | None:
        """Like first(), but locks the row until the transaction ends, so two
        refreshes of the same session run one after the other."""
        raise NotImplementedError

    def revoke_all_for_user(
        self,
        user_id: int,
        now: datetime,
        keep_session_id: int | None = None,
        tenant_id: UUID | None = None,
    ) -> int:
        """Revoke the user's active sessions (only those of `tenant_id`, if
        given) except `keep_session_id`; return how many were revoked."""
        raise NotImplementedError


class LoginFailureRepository(ABC):
    """Failed logins, counted per username or per client IP"""

    @abstractmethod
    def add(self, failure: LoginFailure) -> None: ...

    @abstractmethod
    def last_failure_at(
        self, *, username: str | None = None, ip_address: str | None = None
    ) -> datetime | None:
        """When the most recent failure for that username (or IP) happened"""

    @abstractmethod
    def count_since(
        self,
        since: datetime,
        *,
        username: str | None = None,
        ip_address: str | None = None,
    ) -> int:
        """Failures for that username (or IP) after `since`"""

    @abstractmethod
    def clear_for_username(self, username: str) -> None: ...

    @abstractmethod
    def purge_before(self, before: datetime) -> None:
        """Delete failures too old to matter for any lockout"""
