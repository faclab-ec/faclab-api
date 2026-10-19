from abc import ABC, abstractmethod
from collections.abc import Iterable
from uuid import UUID

from src.shared.app.repositories import Repository
from src.tenancy.app.types import TenantAccess
from src.tenancy.domain.entities import Membership, Tenant


class TenantRepository(ABC):
    @abstractmethod
    def add(self, tenant: Tenant) -> Tenant: ...

    @abstractmethod
    def update(self, tenant: Tenant) -> Tenant: ...

    @abstractmethod
    def get(self, tenant_id: UUID) -> Tenant | None: ...

    @abstractmethod
    def get_by_ruc(self, ruc: str) -> Tenant | None: ...

    @abstractmethod
    def get_many(self, tenant_ids: Iterable[UUID]) -> list[Tenant]: ...


class MembershipRepository(Repository[Membership]):
    @abstractmethod
    def get_for(
        self, tenant_id: UUID, user_id: int, for_update: bool = False
    ) -> Membership | None:
        """The user's membership in the tenant, active or not; `for_update`
        locks it until the transaction ends."""

    @abstractmethod
    def active_accesses(self, user_id: int) -> list[TenantAccess]:
        """Active memberships of the user in active tenants, by tenant name"""

    @abstractmethod
    def active_access(self, user_id: int, tenant_id: UUID) -> TenantAccess | None:
        """The user's access to that tenant, if both are active"""

    @abstractmethod
    def lock_active_admins(self, tenant_id: UUID) -> int:
        """Lock the tenant's active admin memberships (of active users) until
        the transaction ends and return how many there are, so two requests
        that demote admins run one after the other."""

    @abstractmethod
    def has_active_elsewhere(self, user_id: int, tenant_id: UUID) -> bool:
        """Whether the user has an active membership in another tenant"""

    @abstractmethod
    def branch_ids(self, membership_id: int) -> list[int]:
        """The branches the membership is limited to, sorted; empty when it
        may enter all of them"""

    @abstractmethod
    def set_branches(self, membership: Membership, branch_ids: Iterable[int]) -> None:
        """Replace the membership's branches; none means all of them"""
