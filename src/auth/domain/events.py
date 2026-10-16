from dataclasses import dataclass
from typing import Any

from src.shared.domain.events import DomainEvent


@dataclass
class UserCreated(DomainEvent):
    user_id: int = 0
    username: str = ""
    email: str = ""
    role: int = 0  # in the tenant it was created in (`tenant_id`)

    def _payload(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
            "tenant_id": str(self.tenant_id) if self.tenant_id else None,
            "role": self.role,
        }


@dataclass
class UserLoggedIn(DomainEvent):
    user_id: int = 0
    username: str = ""

    def _payload(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
        }


@dataclass
class UserPasswordChanged(DomainEvent):
    user_id: int = 0
    username: str = ""

    def _payload(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
        }


@dataclass
class UserPasswordReset(DomainEvent):
    user_id: int = 0
    username: str = ""
    reset_by_user_id: int = 0

    def _payload(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "reset_by_user_id": self.reset_by_user_id,
        }
