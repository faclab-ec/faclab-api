from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from src.shared.app.repositories import Repository
from src.webhooks.domain.entities import (
    Subscriber,
    WebhookDelivery,
    WebhookDeliveryStatus,
    WebhookEndpoint,
    WebhookEndpointStatus,
)


class WebhookEndpointRepository(Repository[WebhookEndpoint]):
    @abstractmethod
    def first_for_update(self, **kwargs) -> WebhookEndpoint | None:
        """Locks the endpoint until the transaction ends"""

    @abstractmethod
    def page(
        self,
        owner_id: int | None,
        status: WebhookEndpointStatus | None,
        limit: int | None,
        offset: int | None,
    ) -> tuple[list[WebhookEndpoint], int]:
        """The tenant's endpoints (of one integration client with `owner_id`)
        by id, and how many there are"""

    @abstractmethod
    def of_owner(self, owner_id: int) -> list[WebhookEndpoint]:
        """The endpoints of an integration client, by id"""

    @abstractmethod
    def remove(self, endpoint_id: int) -> None:
        """Deletes the endpoint with its deliveries"""


class WebhookDeliveryRepository(Repository[WebhookDelivery]):
    @abstractmethod
    def first_for_update(self, **kwargs) -> WebhookDelivery | None: ...

    @abstractmethod
    def history(
        self,
        endpoint_id: int,
        since: datetime,
        status: WebhookDeliveryStatus | None,
        event_type: str | None,
        limit: int | None,
        offset: int | None,
    ) -> tuple[list[dict], int]:
        """The endpoint's deliveries created since `since`, newest first, with
        their message's id and type"""

    @abstractmethod
    def describe(self, delivery_id: int) -> dict | None:
        """One delivery as `history` shows it"""


class WebhookQueue(ABC):
    """The webhooks outbox: messages and their deliveries, written in the
    transaction of what they tell"""

    @abstractmethod
    def subscribers(self) -> list[Subscriber]:
        """The tenant's active endpoints, without the ones of a revoked client.
        The same within a transaction: an event of each line of a sale asks
        once"""

    @abstractmethod
    def client_public_id(self, client_id: int) -> str | None:
        """The `azp` of an integration client of the tenant"""

    @abstractmethod
    def enqueue(
        self,
        public_id: str,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: datetime,
        origin_integration_id: int | None,
        endpoint_ids: Iterable[int],
    ) -> list[int]:
        """A message and a pending delivery to each endpoint; their ids"""
