from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from src.auth.domain.entities import Role
from src.shared.domain.entities import Entity
from src.shared.domain.exceptions import InvalidValueError
from src.shared.domain.value_objects import TaxId
from src.tenancy.domain.exceptions import (
    OffboardingAlreadyStartedError,
    OffboardingNotStartedError,
    TenantOffboardedError,
)


class TenantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    # Its personal data was anonymized and its access removed after the grace
    # period (S8.7); only what tax law requires is kept, until the retention ends
    OFFBOARDED = "offboarded"


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
    # The termination of the contract (S8.7): started (read-only, exports open)
    # until `grace_ends_at`, anonymized, and deletable once `retention_ends_at`
    # (the tax retention of what was issued) has passed
    offboarding_started_at: datetime | None = None
    grace_ends_at: datetime | None = None
    retention_ends_at: datetime | None = None
    anonymized_at: datetime | None = None

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
        if self.status == TenantStatus.OFFBOARDED:
            raise TenantOffboardedError()
        self.status = TenantStatus.ACTIVE

    @property
    def in_offboarding(self) -> bool:
        return self.offboarding_started_at is not None

    def start_offboarding(
        self, now: datetime, grace_ends_at: datetime, retention_ends_at: datetime
    ) -> None:
        if self.status == TenantStatus.OFFBOARDED:
            raise TenantOffboardedError()
        if self.in_offboarding:
            raise OffboardingAlreadyStartedError()
        self.offboarding_started_at = now
        self.grace_ends_at = grace_ends_at
        self.retention_ends_at = retention_ends_at

    def cancel_offboarding(self) -> None:
        """Back to normal, only while its data is still whole"""
        if self.status == TenantStatus.OFFBOARDED:
            raise TenantOffboardedError()
        if not self.in_offboarding:
            raise OffboardingNotStartedError()
        self.offboarding_started_at = None
        self.grace_ends_at = None
        self.retention_ends_at = None

    def mark_anonymized(self, now: datetime) -> None:
        self.status = TenantStatus.OFFBOARDED
        self.anonymized_at = now


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
