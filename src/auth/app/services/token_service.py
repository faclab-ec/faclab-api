from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from src.auth.domain.entities import User

TokenType = Literal["access", "refresh"]


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "Bearer"


@dataclass(frozen=True)
class TokenClaims:
    sub: int
    username: str
    role: int
    typ: TokenType
    iat: int
    exp: int
    iss: str
    must_change_password: bool = False
    sid: int | None = None  # AuthSession id; tokens issued before sessions have none
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
    def issue_pair(self, user: User, session_id: int, refresh_jti: str) -> TokenPair:
        """Access and refresh tokens of the session; the refresh token carries
        `refresh_jti`, the rotation the session currently accepts."""

    @abstractmethod
    def decode_access(self, token: str) -> TokenClaims: ...

    @abstractmethod
    def decode_refresh(self, token: str) -> TokenClaims: ...
