import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.shared.domain.tenant import current_tenant_id


@dataclass
class DomainEvent(ABC):
    aggregate_id: int
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    # The tenant of the context it was raised in; explicit only in platform
    # tasks that act on a tenant without being inside it
    tenant_id: UUID | None = field(default_factory=current_tenant_id)

    @abstractmethod
    def _payload(self) -> dict[str, Any]:
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.__class__.__name__,
            "aggregate_id": self.aggregate_id,
            "tenant_id": str(self.tenant_id) if self.tenant_id else None,
            "occurred_at": self.occurred_at.isoformat(),
            "payload": self._payload(),
        }
