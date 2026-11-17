from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import date, datetime

from src.integrations.domain.entities import (
    ClientSecret,
    IntegrationClient,
    IntegrationClientStatus,
)
from src.shared.app.repositories import Repository


class IntegrationClientRepository(Repository[IntegrationClient]):
    @abstractmethod
    def first_for_update(self, **kwargs) -> IntegrationClient | None:
        """Locks the client until the transaction ends: its secrets change one
        request at a time"""

    @abstractmethod
    def page(
        self,
        status: IntegrationClientStatus | None,
        limit: int | None,
        offset: int | None,
    ) -> tuple[list[IntegrationClient], int]:
        """The tenant's clients by id, and how many there are"""


class ClientSecretRepository(Repository[ClientSecret]):
    @abstractmethod
    def of_clients(self, client_ids: Iterable[int]) -> list[ClientSecret]:
        """Every secret of those clients, revoked ones included, by id"""


class IntegrationDirectory(ABC):
    """Which tenant a client_id belongs to, readable before any tenant is
    known: the token endpoint starts from the client_id alone"""

    @abstractmethod
    def add(self, public_id: str) -> None:
        """Registers a new client of the context's tenant"""


class IntegrationUsageRepository(ABC):
    """Usage of each client per day: counters, never one row per request"""

    @abstractmethod
    def count(
        self,
        client_id: int,
        *,
        at: datetime,
        ip: str | None = None,
        token_requests: int = 0,
        token_failures: int = 0,
        requests: int = 0,
        errors: int = 0,
    ) -> None:
        """Adds to the counters of the day of `at`"""

    @abstractmethod
    def days(self, client_id: int, from_day: date, to_day: date) -> list[dict]:
        """The client's days with usage between both, oldest first"""
