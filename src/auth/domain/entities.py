from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum
from uuid import UUID

from src.shared.domain.entities import Entity


class Role(IntEnum):
    ADMIN = 1
    MANAGER = 2
    OPERATOR = 3
    VIEWER = 4
    CASHIER = 5


@dataclass
class User(Entity):
    """Identidad global: el usuario y el email son únicos en la plataforma.
    El rol vive en cada membresía (`src/tenancy`); `is_active` bloquea la
    cuenta en todas las empresas."""

    username: str
    email: str
    password_hash: str
    id: int | None = None
    is_active: bool = True
    must_change_password: bool = False
    last_login_at: datetime | None = None
    created_at: datetime | None = None
    full_name: str | None = None

    @property
    def display_name(self) -> str:
        """Nombre que se guarda como autor en los documentos"""
        return self.full_name or self.username

    def activate(self) -> None:
        self.is_active = True

    def deactivate(self) -> None:
        self.is_active = False

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

    def rename(self, full_name: str | None) -> None:
        self.full_name = (full_name or "").strip() or None


@dataclass
class AuthSession(Entity):
    """Sesión abierta con un login.

    Pertenece a una empresa (`tenant_id`): sus tokens llevan esa empresa
    (`tid`) y su id (`sid`). El refresh solo funciona mientras la
    sesión esté activa, así que revocarla (logout, cambio de contraseña,
    desactivar al usuario) cierra la sesión aunque el refresh token no haya
    vencido. Cada refresh extiende su vencimiento.

    El refresh token rota: solo el que lleva `refresh_jti` es válido. El
    inmediatamente anterior se acepta durante una gracia corta después de
    rotar (dos pestañas que refrescan a la vez); cualquier otro ya usado
    indica robo y revoca la sesión.
    """

    user_id: int
    expires_at: datetime
    tenant_id: UUID
    id: int | None = None
    revoked_at: datetime | None = None
    created_at: datetime | None = None
    refresh_jti: str | None = None
    previous_refresh_jti: str | None = None
    refreshed_at: datetime | None = None

    def is_active(self, now: datetime) -> bool:
        return self.revoked_at is None and self.expires_at > now

    def revoke(self, now: datetime) -> None:
        if self.revoked_at is None:
            self.revoked_at = now

    def extend(self, until: datetime) -> None:
        self.expires_at = until

    def rotate(self, new_jti: str, now: datetime) -> None:
        self.previous_refresh_jti = self.refresh_jti
        self.refresh_jti = new_jti
        self.refreshed_at = now

    def accepts_previous(self, jti: str, now: datetime, grace: timedelta) -> bool:
        """El token recién reemplazado, presentado dentro de la gracia"""
        return (
            self.previous_refresh_jti is not None
            and jti == self.previous_refresh_jti
            and self.refreshed_at is not None
            and now - self.refreshed_at <= grace
        )


@dataclass
class LoginFailure(Entity):
    """Un intento de login fallido, contado para el bloqueo"""

    username: str
    attempted_at: datetime
    ip_address: str | None = None
    id: int | None = None


@dataclass(frozen=True)
class LoginLockoutPolicy:
    """`max_failures` fallas dentro de `window` bloquean el usuario (o la IP)
    durante `lockout`, contado desde la última falla."""

    max_failures_per_user: int = 5
    max_failures_per_ip: int = 20
    window: timedelta = timedelta(minutes=15)
    lockout: timedelta = timedelta(minutes=15)

    @property
    def retention(self) -> timedelta:
        """Hasta cuándo una falla todavía puede influir en un bloqueo"""
        return max(self.window, self.lockout)


@dataclass(frozen=True)
class AuthenticatedUser:
    """Quien hace la solicitud, según su access token: el rol y los permisos
    son los de su membresía en la empresa `tenant_id`."""

    id: int
    username: str
    role: Role
    tenant_id: UUID
    permissions: frozenset = field(default_factory=frozenset)
    must_change_password: bool = False
    session_id: int | None = None
    full_name: str | None = None
    # Sucursales a las que puede entrar (claim `bids`); None son todas
    branch_ids: frozenset[int] | None = None

    @property
    def display_name(self) -> str:
        """Nombre que se guarda como autor de lo que hace este usuario"""
        return self.full_name or self.username

    def can_enter_branch(self, branch_id: int) -> bool:
        return self.branch_ids is None or branch_id in self.branch_ids
