from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from src.auth.domain.entities import Role
from src.shared.domain.entities import Entity
from src.shared.domain.exceptions import InvalidValueError
from src.shared.domain.value_objects import TaxId


class TenantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


@dataclass
class Tenant:
    """Una empresa cliente de la plataforma: un contribuyente con un RUC.

    No extiende `Entity` porque su id es un UUID generado aquí, no un entero
    de la base.
    """

    ruc: str
    legal_name: str
    trade_name: str | None = None
    status: TenantStatus = TenantStatus.ACTIVE
    id: UUID = field(default_factory=uuid4)
    created_at: datetime | None = None

    def __post_init__(self):
        self.ruc = self.ruc.strip()
        if len(self.ruc) != 13:
            raise InvalidValueError(f"RUC must have 13 digits: {self.ruc}")
        TaxId(self.ruc)
        self.legal_name = self.legal_name.strip()
        if not self.legal_name:
            raise InvalidValueError("legal name is required")
        self.trade_name = (self.trade_name or "").strip() or None

    def dict(self):
        return self.__dict__

    @property
    def is_active(self) -> bool:
        return self.status == TenantStatus.ACTIVE

    def suspend(self) -> None:
        self.status = TenantStatus.SUSPENDED

    def activate(self) -> None:
        self.status = TenantStatus.ACTIVE


@dataclass
class Membership(Entity):
    """El rol de un usuario (identidad global) dentro de una empresa"""

    tenant_id: UUID
    user_id: int
    role: Role = Role.VIEWER
    active: bool = True
    id: int | None = None
    created_at: datetime | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    def change_role(self, role: Role) -> None:
        self.role = role

    def activate(self) -> None:
        self.active = True

    def deactivate(self) -> None:
        self.active = False
