from abc import ABC, abstractmethod
from collections.abc import Collection
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from src.auth.domain.entities import User
from src.auth.domain.scopes import Scope
from src.tenancy.domain.entities import Membership

TokenType = Literal["access", "refresh", "selection", "platform"]


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "Bearer"


@dataclass(frozen=True)
class SelectionToken:
    """Proves the password was right; only good for choosing a tenant"""

    token: str
    expires_in: int


@dataclass(frozen=True)
class TokenClaims:
    sub: int
    username: str
    typ: TokenType
    iat: int
    exp: int
    iss: str
    role: int | None = None  # the membership's role; selection tokens have none
    tid: UUID | None = None  # the session's tenant; selection tokens have none
    must_change_password: bool = False
    sid: int | None = None  # AuthSession id; selection tokens have none
    jti: str | None = None  # refresh tokens only: which rotation of the session
    name: str | None = None  # access tokens only: the user's full name, if set
    # access tokens only: the branches the user may enter; None means all
    bids: frozenset[int] | None = None


@dataclass(frozen=True)
class ClientToken:
    """The access token of an integration client (S6.2): no refresh, it asks
    for another one with its credentials"""

    access_token: str
    expires_in: int
    scopes: frozenset[Scope]
    token_type: str = "Bearer"


@dataclass(frozen=True)
class ClientTokenClaims:
    """An integration's access token: `sub` is `client:<public_id>`"""

    public_id: str  # `azp`, the client_id of OAuth
    tid: UUID
    secret_id: int  # `cred`: the secret it was obtained with
    scopes: frozenset[Scope]
    iat: int
    exp: int
    iss: str
    # The branches it was limited to when issued; None means all
    bids: frozenset[int] | None = None


@dataclass(frozen=True)
class PlatformToken:
    """The access token of a platform operator (S8.5): no tenant, short-lived,
    no refresh (it logs in again)"""

    access_token: str
    expires_in: int
    token_type: str = "Bearer"


@dataclass(frozen=True)
class PlatformTokenClaims:
    """A platform operator's token: `typ` is `platform`, it has no `tid`"""

    sub: int  # the user
    username: str
    iat: int
    exp: int
    iss: str
    name: str | None = None


class TokenService(ABC):
    @property
    @abstractmethod
    def refresh_ttl_seconds(self) -> int:
        """How long a session lasts without refreshing"""

    @property
    @abstractmethod
    def refresh_reuse_grace_seconds(self) -> int:
        """How long the refresh token just replaced is still accepted"""

    @abstractmethod
    def issue_pair(
        self,
        user: User,
        membership: Membership,
        session_id: int,
        refresh_jti: str,
        *,
        branch_ids: Collection[int] | None = None,
    ) -> TokenPair:
        """Access and refresh tokens of the session, for the membership's tenant
        (`tid`) and role; the refresh token carries `refresh_jti`, the rotation
        the session currently accepts. `branch_ids` are the branches the
        membership is limited to (`bids` in the access token); None, all."""

    @abstractmethod
    def issue_selection(self, user: User) -> SelectionToken:
        """Short-lived token of a user with several tenants, exchanged for a
        pair in POST /api/auth/select-tenant"""

    @abstractmethod
    def decode_access(self, token: str) -> TokenClaims:
        """Raises TenantRequiredError when the token has no tenant"""

    @abstractmethod
    def decode_refresh(self, token: str) -> TokenClaims: ...

    @abstractmethod
    def decode_selection(self, token: str) -> TokenClaims:
        """A selection token, or an access token of a user switching tenants"""

    @abstractmethod
    def issue_client_access(
        self,
        *,
        public_id: str,
        tenant_id: UUID,
        secret_id: int,
        scopes: Collection[Scope],
        branch_ids: Collection[int] | None = None,
    ) -> ClientToken:
        """Access token of an integration client of `tenant_id`, obtained with
        its secret `secret_id`, with those scopes and limited to `branch_ids`
        (None, all of them)"""

    @abstractmethod
    def issue_platform_access(self, user: User) -> PlatformToken:
        """Token of a platform operator: for this service only (never the
        audiences of the other services), with no tenant"""

    @abstractmethod
    def decode_bearer(
        self, token: str
    ) -> TokenClaims | ClientTokenClaims | PlatformTokenClaims:
        """An access token of a user (as `decode_access`), of an integration
        client or of a platform operator. The user methods never accept the
        other two"""
