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


class TokenService(ABC):
    @property
    @abstractmethod
    def refresh_ttl_seconds(self) -> int:
        """How long a session lasts without refreshing"""

    @abstractmethod
    def issue_pair(self, user: User, session_id: int) -> TokenPair: ...

    @abstractmethod
    def decode_access(self, token: str) -> TokenClaims: ...

    @abstractmethod
    def decode_refresh(self, token: str) -> TokenClaims: ...
