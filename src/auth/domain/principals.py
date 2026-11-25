from dataclasses import dataclass
from uuid import UUID

from src.auth.domain.entities import AuthenticatedUser
from src.auth.domain.permissions import Permission
from src.auth.domain.scopes import Scope, permissions_for_scopes


@dataclass(frozen=True)
class IntegrationPrincipal:
    """An integration client of the tenant `tenant_id` making a request with
    its access token (S6.2). Its scopes and branches are those of the token
    narrowed to what the client has now, so taking a scope or a branch away
    applies within the status cache, before the token expires."""

    client_id: int  # the client's row
    public_id: str  # its client_id in OAuth (`azp`), fl_live_… / fl_test_…
    name: str
    tenant_id: UUID
    scopes: frozenset[Scope]
    # Branches it may operate in; None, all of them
    branch_ids: frozenset[int] | None = None

    @property
    def permissions(self) -> frozenset[Permission]:
        return permissions_for_scopes(self.scopes)

    @property
    def display_name(self) -> str:
        """The author of what it does, like a user's full name"""
        return self.name

    def can_enter_branch(self, branch_id: int) -> bool:
        return self.branch_ids is None or branch_id in self.branch_ids

    def has_scopes(self, *scopes: Scope) -> bool:
        return set(scopes).issubset(self.scopes)


# Whoever makes an authenticated request: a person or an integration
Principal = AuthenticatedUser | IntegrationPrincipal


@dataclass(frozen=True)
class PlatformPrincipal:
    """An operator of the platform (S8.5): a user with a row in
    `platform_operators`, authenticated with a `platform` token. It has no
    tenant: it only reaches `/api/platform`."""

    user_id: int
    username: str
    full_name: str | None = None

    @property
    def display_name(self) -> str:
        return self.full_name or self.username
