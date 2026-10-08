from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum

from src.shared.domain.entities import Entity


class Role(IntEnum):
    ADMIN = 1
    MANAGER = 2
    OPERATOR = 3
    VIEWER = 4
    CASHIER = 5


@dataclass
class User(Entity):
    username: str
    email: str
    password_hash: str
    role: Role = Role.VIEWER
    id: int | None = None
    is_active: bool = True
    must_change_password: bool = False
    last_login_at: datetime | None = None
    created_at: datetime | None = None

    def activate(self) -> None:
        self.is_active = True

    def deactivate(self) -> None:
        self.is_active = False

    def change_role(self, role: Role) -> None:
        self.role = role

    def change_password(self, password_hash: str) -> None:
        """El usuario fijó su propia contraseña"""
        self.password_hash = password_hash
        self.must_change_password = False

    def reset_password(self, password_hash: str) -> None:
        """Un admin asignó una contraseña temporal que el usuario debe cambiar"""
        self.password_hash = password_hash
        self.must_change_password = True

    def record_login(self, at: datetime) -> None:
        self.last_login_at = at


@dataclass(frozen=True)
class AuthenticatedUser:
    id: int
    username: str
    role: Role
    permissions: frozenset = field(default_factory=frozenset)
    must_change_password: bool = False
