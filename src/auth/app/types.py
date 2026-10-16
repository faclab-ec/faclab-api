from dataclasses import dataclass
from typing import Any

from src.auth.domain.entities import User
from src.tenancy.domain.entities import Membership


@dataclass(frozen=True)
class TenantMember:
    """Un usuario visto desde una empresa: su rol y si está activo son los de
    su membresía en ella"""

    user: User
    membership: Membership

    def dict(self) -> dict[str, Any]:
        return {
            **self.user.dict(),
            "role": self.membership.role,
            "is_active": self.membership.active,
        }
