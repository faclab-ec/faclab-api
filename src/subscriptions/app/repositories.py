from abc import ABC, abstractmethod
from datetime import date

from src.shared.app.plans import PlanResource
from src.shared.app.repositories import Repository
from src.subscriptions.domain.entities import DocumentUsage, Plan, Subscription


class PlanRepository(Repository[Plan], ABC):
    """Platform rows: every tenant reads them, only the platform writes them"""

    @abstractmethod
    def default(self) -> Plan | None:
        """The plan new tenants get"""


class SubscriptionRepository(Repository[Subscription], ABC):
    @abstractmethod
    def current(self) -> Subscription | None:
        """The context tenant's"""

    @abstractmethod
    def lock_current(self) -> Subscription | None:
        """The context tenant's, locked until the transaction ends"""


class DocumentUsageRepository(ABC):
    @abstractmethod
    def count(
        self, period: date, *, invoices: int = 0, credit_notes: int = 0
    ) -> DocumentUsage:
        """Adds to the context tenant's month and returns its new totals"""

    @abstractmethod
    def months(self, periods: list[date]) -> list[DocumentUsage]:
        """The context tenant's usage of each period (zero when it has none)"""


class TenantUsage(ABC):
    @abstractmethod
    def count(self, resource: PlanResource) -> int:
        """How many of `resource` the context tenant has, as its plan counts
        them: active branches, terminals and users, clients not revoked and
        every webhook endpoint"""
