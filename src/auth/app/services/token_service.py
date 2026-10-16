from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from src.auth.domain.entities import User
from src.tenancy.domain.entities import Membership

TokenType = Literal["access", "refresh", "selection"]


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
        self, user: User, membership: Membership, session_id: int, refresh_jti: str
    ) -> TokenPair:
        """Access and refresh tokens of the session, for the membership's tenant
        (`tid`) and role; the refresh token carries `refresh_jti`, the rotation
        the session currently accepts."""

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
