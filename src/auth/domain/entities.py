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


@dataclass
class AuthSession(Entity):
    """Sesión abierta con un login.

    Sus tokens llevan su id (`sid`). El refresh solo funciona mientras la
    sesión esté activa, así que revocarla (logout, cambio de contraseña,
    desactivar al usuario) cierra la sesión aunque el refresh token no haya
    vencido. Cada refresh extiende su vencimiento.
    """

    user_id: int
    expires_at: datetime
    id: int | None = None
    revoked_at: datetime | None = None
    created_at: datetime | None = None

    def is_active(self, now: datetime) -> bool:
        return self.revoked_at is None and self.expires_at > now

    def revoke(self, now: datetime) -> None:
        if self.revoked_at is None:
            self.revoked_at = now

    def extend(self, until: datetime) -> None:
        self.expires_at = until


@dataclass(frozen=True)
class AuthenticatedUser:
    id: int
    username: str
    role: Role
    permissions: frozenset = field(default_factory=frozenset)
    must_change_password: bool = False
    session_id: int | None = None
